from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import OVSKernelSwitch
from mininet.cli import CLI
from mininet.node import Host
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import time
import numpy as np

class ReorderTopo(Topo):
    def build(self):
        switch = self.addSwitch('s1')
        server = self.addHost('server', ip='10.0.0.1/24')
        self.addLink(server, switch, cls=TCLink, bw=10, delay='50ms')  # 기본, reordering은 netem으로
        for i in range(2, 8):  # 6 clients
            client = self.addHost(f'client{i-1}', ip=f'10.0.0.{i}/24')
            self.addLink(client, switch, cls=TCLink, bw=10, delay='50ms')

def measure_reorder_performance(net):
    # Reordering 시뮬: 클라이언트 인터페이스에 netem 적용
    for i in range(1, 7):
        client = net.get(f'client{i}')
        client.cmd('tc qdisc add dev client{i}-eth0 root netem reorder 10% 50%')  # 10% 재정렬, 50% 상관
    
    server = net.get('server')
    server.cmd('iperf -s &')
    
    clients = [net.get(f'client{i}') for i in range(1, 7)]
    throughputs = []
    for client in clients:
        result = client.cmd('iperf -c 10.0.0.1 -t 30')
        lines = result.split('\n')
        throughput_line = [line for line in lines if 'sec' in line][-1]
        throughput = float(throughput_line.split()[-2]) / 1e6 if throughput_line else 0  # Mbps
        throughputs.append(throughput)
    
    total_throughput = sum(throughputs)
    utilization = total_throughput / 10.0  # Mbps (of 10Mbps link)
    
    n = len(throughputs)
    jain = (np.sum(throughputs)**2) / (n * np.sum(np.square(throughputs))) if np.sum(throughputs) > 0 else 0
    
    ping_result = clients[0].cmd('ping -c 10 10.0.0.1')
    latency_avg = float(ping_result.split('/')[-3]) if 'rtt' in ping_result else 0
    
    info(f"Utilization: {utilization:.2f} (of 10Mbps), Fairness: {jain:.2f}, Latency: {latency_avg:.2f} ms\n")
    return utilization, jain, latency_avg

def main():
    topo = ReorderTopo()
    net = Mininet(topo=topo, switch=OVSKernelSwitch, link=TCLink)
    net.start()
    measure_reorder_performance(net)
    CLI(net)
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    main()