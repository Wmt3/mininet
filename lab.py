#!/usr/bin/env python3
# test_reno_problem.py
# 목적: Reno의 공정성 문제를 실시간으로 측정

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import OVSKernelSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
import subprocess
import time
import threading
import json

class MultiFlowTopology(Topo):
    """10개 호스트 → 스위치 → 병목(1Mbps) → 도착지"""
    def build(self):
        # 10개 송신 호스트
        sender_hosts = []
        for i in range(1, 11):
            h = self.addHost(f'h{i}')
            sender_hosts.append(h)
        
        # 1개 수신 호스트
        receiver = self.addHost('receiver')
        
        # 스위치
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch)
        
        # 송신자 → 스위치: 무제한 대역폭
        for h in sender_hosts:
            self.addLink(h, s1, cls=TCLink, bw=100)
        
        # 스위치 → 수신자: 병목 1Mbps (문제를 일으킬 환경)
        # loss=1 (1% 패킷 손실) + delay=100ms (RTT=200ms)
        self.addLink(s1, receiver, cls=TCLink, bw=1, delay='100ms', loss=1)

def measure_fairness(net, duration=30):
    """
    Jain's Fairness Index 계산
    
    공식: FI = (Σ throughput)^2 / (N * Σ throughput^2)
    - FI = 1: 완벽한 공정성
    - FI < 0.5: 심각한 불공정
    """
    receiver = net.get('receiver')
    senders = [net.get(f'h{i}') for i in range(1, 11)]
    
    # iperf3 서버 시작 (수신자)
    receiver.cmd('iperf3 -s -D &')
    time.sleep(1)
    
    results = {
        'time': [],
        'throughputs': [[] for _ in range(10)],
        'fairness_index': [],
        'total_utilization': [],
        'link_utilization': []
    }
    
    try:
        # 각 송신자에서 병렬로 iperf3 클라이언트 시작
        for i, sender in enumerate(senders):
            sender.cmd(f'iperf3 -c {receiver.IP()} -t {duration} -i 1 '
                      f'> /tmp/iperf_h{i+1}.txt &')
        
        start = time.time()
        interval = 2  # 2초마다 측정
        
        while time.time() - start < duration:
            time.sleep(interval)
            elapsed = int(time.time() - start)
            results['time'].append(elapsed)
            
            # 각 플로우의 처리량 읽기 (iperf3 출력 파싱)
            throughputs = []
            for i in range(10):
                bw = _parse_iperf_bandwidth(f'/tmp/iperf_h{i+1}.txt')
                throughputs.append(bw)
                results['throughputs'][i].append(bw)
            
            # Jain's Fairness Index 계산
            total_tp = sum(throughputs)
            sum_sq = sum(tp**2 for tp in throughputs)
            
            if sum_sq > 0:
                fi = (total_tp**2) / (10 * sum_sq)
            else:
                fi = 0
            
            results['fairness_index'].append(fi)
            results['total_utilization'].append(total_tp / 10)  # 평균
            results['link_utilization'].append(total_tp / 1.0)  # 1Mbps 기준
            
            info(f"[{elapsed}s] FI={fi:.3f}, AvgTP={total_tp/10:.2f}Mbps, "
                 f"LinkUtil={total_tp:.2f}%, MaxFlow={max(throughputs):.2f}Mbps, "
                 f"MinFlow={min(throughputs):.2f}Mbps\n")
    
    finally:
        # 정리
        receiver.cmd('pkill -f iperf3')
        for i in range(10):
            senders[i].cmd('pkill -f iperf3')
    
    return results

def _parse_iperf_bandwidth(filename):
    """iperf3 출력 파일에서 최신 대역폭 추출"""
    try:
        with open(filename, 'r') as f:
            lines = f.readlines()
        
        # 마지막 유효한 대역폭 라인 찾기
        for line in reversed(lines):
            if 'Mbps' in line:
                parts = line.split()
                for j, part in enumerate(parts):
                    if 'Mbps' in part and j > 0:
                        try:
                            return float(parts[j-1])
                        except ValueError:
                            pass
        return 0.0
    except:
        return 0.0

def main():
    setLogLevel('info')
    
    topo = MultiFlowTopology()
    net = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    
    net.start()
    
    info("\n" + "="*70)
    info("TCP Reno 문제 실험: 다중 플로우 공정성 측정")
    info("="*70 + "\n")
    
    # 토폴로지 정보
    info(f"토폴로지: 10개 송신자 → 1Mbps 병목 링크 → 1개 수신자\n")
    info(f"네트워크 조건: 1Mbps BW, 100ms 지연(왕복 200ms), 1% 손실률\n")
    info(f"측정 시간: 30초\n\n")
    
    results = measure_fairness(net, duration=30)
    
    # 결과 분석
    info("\n" + "="*70)
    info("실험 결과 분석")
    info("="*70 + "\n")
    
    avg_fi = sum(results['fairness_index']) / len(results['fairness_index'])
    avg_util = sum(results['link_utilization']) / len(results['link_utilization'])
    
    info(f"평균 Jain's Fairness Index: {avg_fi:.3f}\n")
    info(f"평균 링크 활용도: {avg_util:.1f}% (이상적: 100%)\n")
    info(f"플로우별 평균 처리량 (Mbps):\n")
    
    for i, tps in enumerate(results['throughputs']):
        avg_tp = sum(tps) / len(tps) if tps else 0
        min_tp = min(tps) if tps else 0
        max_tp = max(tps) if tps else 0
        info(f"  Flow {i+1:2d}: 평균={avg_tp:.3f}, 최소={min_tp:.3f}, 최대={max_tp:.3f}\n")
    
    info("\n" + "="*70)
    if avg_fi < 0.5:
        info("⚠️  결론: Reno는 심각한 공정성 문제 보유 (FI < 0.5)")
    elif avg_fi < 0.8:
        info("⚠️  결론: Reno는 중간 정도의 공정성 문제 보유 (0.5 ≤ FI < 0.8)")
    else:
        info("✓ Reno는 충분한 공정성 수준")
    info("="*70 + "\n")
    
    # JSON으로 저장
    with open('/tmp/reno_problem_results.json', 'w') as f:
        json.dump({
            'fairness_index': results['fairness_index'],
            'link_utilization': results['link_utilization'],
            'avg_fairness': avg_fi,
            'avg_utilization': avg_util
        }, f, indent=2)
    
    net.stop()

if __name__ == '__main__':
    main()
