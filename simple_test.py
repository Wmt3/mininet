#!/usr/bin/env python3
# improved_measure.py

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.node import OVSKernelSwitch
from mininet.log import setLogLevel
import time
import json
import re
from multiprocessing import Pool

class RealBottleneckTopology(Topo):
    def build(self):
        # 송신자 그룹
        senders = [self.addHost(f'h{i}') for i in range(1, 6)]
        # 수신자 그룹  
        receivers = [self.addHost(f'h{i+5}') for i in range(1, 6)]
        
        # 두 개의 스위치 + 중간 병목 링크
        s1 = self.addSwitch('s1')  # 송신자쪽
        s2 = self.addSwitch('s2')  # 수신자쪽
        
        # 송신자 → s1: 고속 링크
        for h in senders:
            self.addLink(h, s1, cls=TCLink, bw=10, delay='5ms')
        
        # ★ 핵심: s1 ↔ s2 병목 링크 (1Mbps, RTT 200ms)
        self.addLink(s1, s2, cls=TCLink, bw=1, delay='100ms', loss=0)
        
        # s2 → 수신자: 고속 링크
        for h in receivers:
            self.addLink(s2, h, cls=TCLink, bw=10, delay='5ms')

def run_iperf_client(args):
    """병렬 실행용 함수"""
    h_send, recv_ip, duration = args
    output = h_send.cmd(f'iperf3 -c {recv_ip} -t {duration} -J')
    return output

def main():
    setLogLevel('info')
    
    topo = BottleneckTopology()
    net = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    
    print("\n[1] 네트워크 시작...")
    net.start()
    
    print("[2] IP 설정...")
    for i in range(1, 11):
        h = net.get(f'h{i}')
        h.setIP(f'10.0.0.{i}/24', intf=f'h{i}-eth0')
        print(f"  h{i}: {h.IP()}")
    
    print("\n[3] TCP Congestion Control 설정...")
    for i in range(1, 11):
        h = net.get(f'h{i}')
        h.cmd('sysctl -w net.ipv4.tcp_congestion_control=reno_custom')
    
    print("\n[4] iperf3 서버 시작 (h6~h10)...")
    for i in range(6, 11):
        h = net.get(f'h{i}')
        # 포트를 분리해서 충돌 방지
        h.cmd(f'iperf3 -s -p {5200+i} > /tmp/iperf3_server_{i}.log 2>&1 &')
    
    time.sleep(3)
    print("  서버 시작 완료")
    
    print("\n[5] iperf3 클라이언트 실행 (h1~h5 -> h6~h10)...")
    throughputs = []
    
    for i in range(1, 6):
        h_send = net.get(f'h{i}')
        recv_ip = f'10.0.0.{i+5}'
        port = 5200 + i + 5
        
        print(f"  h{i} -> h{i+5} 테스트 중...")
        result = h_send.cmd(f'iperf3 -c {recv_ip} -p {port} -t 5 -J')
        
        try:
            data = json.loads(result)
            bw_mbps = data['end']['sum_received']['bits_per_second'] / 1e6
            throughputs.append(bw_mbps)
            print(f"    → {bw_mbps:.3f} Mbps")
        except Exception as e:
            print(f"    → 실패: {e}")
            # 실패 원인 확인
            print(f"    결과: {result[:200]}")
    
    print("\n[6] 결과 분석...")
    if throughputs:
        total_bw = sum(throughputs)
        link_capacity = 1.0  # Mbps
        link_util = (total_bw / link_capacity) * 100
        
        # Jain's Fairness Index
        sum_bw = sum(throughputs)
        sum_sq = sum(x**2 for x in throughputs)
        fairness = (sum_bw ** 2) / (len(throughputs) * sum_sq) if sum_sq > 0 else 0
        
        print(f"\n===== 성능 지표 =====")
        print(f"Link Utilization: {link_util:.2f}%")
        print(f"Fairness Index: {fairness:.4f}")
        print(f"개별 Throughput: {[f'{x:.3f}' for x in throughputs]} Mbps")
    
    print("\n[7] 정리...")
    for i in range(6, 11):
        h = net.get(f'h{i}')
        h.cmd('pkill iperf3')
    
    net.stop()

if __name__ == '__main__':
    main()
