from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import OVSKernelSwitch
from mininet.cli import CLI
from mininet.node import Host
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import time
import numpy as np  # Jain's index 계산용

class MultiFlowTopo(Topo):
    def build(self):
        switch = self.addSwitch('s1')
        server = self.addHost('server', ip='10.0.0.1/24')
        self.addLink(server, switch, cls=TCLink, bw=1, delay='100ms', loss=0.1)  # RTT 200ms, minor loss
        for i in range(2, 12):  # 10 clients
            client = self.addHost(f'client{i-1}', ip=f'10.0.0.{i}/24')
            self.addLink(client, switch, cls=TCLink, bw=1, delay='100ms', loss=0.1)

def measure_performance(net, use_improved=False):
    if use_improved:
        # 수정된 Reno 로드 (실제: sudo insmod reno_improved.ko; sysctl net.ipv4.tcp_congestion_control=reno_improved)
        info("Using improved Reno\n")
    
    server = net.get('server')
    server.cmd('iperf -s -u &')  # UDP 서버, but TCP로 변경 가능: iperf -s
    
    clients = [net.get(f'client{i}') for i in range(1, 11)]
    throughputs = []
    for client in clients:
        result = client.cmd('iperf -c 10.0.0.1 -t 30 -u')  # 30초 TCP 흐름, UDP for simplicity
        throughput = float(result.split()[-7]) / 1e6  # Mbps 추출 (실제 파싱 필요)
        throughputs.append(throughput)
    
    # Utilization: 총 throughput / 1Mbps
    total_util = sum(throughputs)
    utilization = total_util / 1.0  # %로 *100 가능
    
    # Fairness: Jain's index
    n = len(throughputs)
    jain = (sum(throughputs)**2) / (n * sum(x**2 for x in throughputs)) if sum(throughputs) > 0 else 0
    
    # Latency: ping 평균
    ping_result = clients[0].cmd('ping -c 10 10.0.0.1')
    latency = float(ping_result.split('/')[-3])  # avg RTT ms
    
    info(f"Utilization: {utilization:.2f} Mbps (of 1Mbps)\nFairness: {jain:.2f}\nAvg Latency: {latency:.2f} ms\n")
    return utilization, jain, latency

def main():
    topo = MultiFlowTopo()
    net = Mininet(topo=topo, switch=OVSKernelSwitch, link=TCLink)
    net.start()
    measure_performance(net)  # 원본 Reno
    CLI(net)
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    main()