#!/usr/bin/env python3
# measure_reno_performance.py

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.node import OVSKernelSwitch
import time
import subprocess
import json
import re

class BottleneckTopology(Topo):
    def build(self):
        senders = [self.addHost(f'h{i}') for i in range(1, 11)]
        receivers = [self.addHost(f'h{i+10}') for i in range(1, 11)]
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, failMode='standalone')
        
        # 모든 링크를 병목 조건으로 설정
        for h in senders:
            self.addLink(h, s1, cls=TCLink, bw=1, delay='100ms', loss=0)
        for h in receivers:
            self.addLink(h, s1, cls=TCLink, bw=1, delay='100ms', loss=0)

def run_experiment(net, duration=10):
    results = {
        'throughputs': [],
        'rtts': [],
        'link_util': 0,
        'fairness': 0
    }
    
    # 1. iperf3 서버 시작 (h11~h20)
    for i in range(11, 21):
        h_recv = net.getNodeByName(f'h{i}')
        h_recv.cmd(f'iperf3 -s -D')  # 데몬 모드
    
    time.sleep(1)
    
    # 2. iperf3 클라이언트 실행 (h1~h10 → h11~h20)
    iperf_outputs = []
    for i in range(1, 11):
        h_send = net.getNodeByName(f'h{i}')
        h_recv_ip = f'10.0.0.{10+i}'
        
        # 각 클라이언트의 throughput 기록
        output = h_send.cmd(
            f'iperf3 -c {h_recv_ip} -t {duration} --json'
        )
        iperf_outputs.append(output)
    
    # 3. 결과 파싱
    throughputs = []
    for output in iperf_outputs:
        try:
            data = json.loads(output)
            bw_mbps = data['end']['sum_received']['bits_per_second'] / 1e6
            throughputs.append(bw_mbps)
        except:
            pass
    
    results['throughputs'] = throughputs
    
    # 4. Link Utilization 계산
    total_bw = sum(throughputs)
    link_capacity = 1  # Mbps (설정한 bw)
    results['link_util'] = (total_bw / link_capacity) * 100
    
    # 5. Fairness 계산 (Jain's Index)
    if throughputs:
        sum_bw = sum(throughputs)
        sum_sq = sum(x**2 for x in throughputs)
        if sum_sq > 0:
            results['fairness'] = (sum_bw ** 2) / (len(throughputs) * sum_sq)
    
    # 6. RTT 측정
    rtts = []
    for i in range(1, 11):
        h_send = net.getNodeByName(f'h{i}')
        h_recv_ip = f'10.0.0.{10+i}'
        ping_out = h_send.cmd(f'ping -c 3 {h_recv_ip}')
        
        match = re.search(r'avg=([0-9.]+)', ping_out)
        if match:
            rtts.append(float(match.group(1)))
    
    results['rtts'] = rtts
    results['rtt_avg'] = sum(rtts) / len(rtts) if rtts else 0
    results['rtt_max'] = max(rtts) if rtts else 0
    
    return results

def main():
    topo = BottleneckTopology()
    net = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    
    net.start()
    
    # TCP congestion control을 reno_custom으로 설정
    for i in range(1, 21):
        h = net.getNodeByName(f'h{i}')
        h.cmd('sysctl -w net.ipv4.tcp_congestion_control=reno_custom')
    
    time.sleep(1)
    
    results = run_experiment(net, duration=10)
    
    print("\n===== RENO Performance Metrics =====")
    print(f"Link Utilization: {results['link_util']:.2f}%")
    print(f"Fairness Index: {results['fairness']:.4f}")
    print(f"Average RTT: {results['rtt_avg']:.2f} ms")
    print(f"Max RTT: {results['rtt_max']:.2f} ms")
    print(f"Individual Throughputs: {[f'{x:.3f}' for x in results['throughputs']]}")
    
    # JSON으로 저장
    with open('reno_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    net.stop()

if __name__ == '__main__':
    main()
