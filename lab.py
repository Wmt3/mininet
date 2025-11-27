#!/usr/bin/env python3
# test_reno_fixed.py
# 실제 동작하는 TCP Reno 문제 측정 코드

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import OVSKernelSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
import subprocess
import time
import threading
import json
import re
import os

class MultiFlowTopology(Topo):
    def build(self):
        sender_hosts = []
        for i in range(1, 11):
            h = self.addHost(f'h{i}')
            sender_hosts.append(h)
        
        receiver = self.addHost('receiver')
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch)
        
        for h in sender_hosts:
            self.addLink(h, s1, cls=TCLink, bw=100)
        
        self.addLink(s1, receiver, cls=TCLink, bw=1, delay='100ms', loss=1)

def run_iperf_test(sender, receiver_ip, flow_id, duration):
    """
    개별 송신자에서 iperf3 실행
    JSON 형식으로 출력하여 파싱 용이
    """
    cmd = (f'iperf3 -c {receiver_ip} -p 5201 -t {duration} '
           f'-i 2 -J > /tmp/iperf_flow{flow_id}.json 2>&1')
    sender.cmd(cmd)

def parse_iperf_json_realtime(filename):
    """
    iperf3 JSON 실시간 파싱
    완성된 파일과 진행 중인 파일 모두 처리
    """
    try:
        if not os.path.exists(filename):
            return []
        
        # 파일이 너무 작으면 아직 쓰기 중
        if os.path.getsize(filename) < 100:
            return []
        
        with open(filename, 'r') as f:
            content = f.read()
        
        # 불완전한 JSON 처리
        if not content.strip().endswith('}'):
            # 마지막 완전한 객체까지만 파싱
            content = content.rsplit('}', 1)[0] + '}'
        
        # 빈 내용 처리
        if len(content) < 50:
            return []
        
        data = json.loads(content)
        bws = []
        
        for interval in data.get('intervals', []):
            sum_data = interval.get('sum', {})
            bits_per_second = sum_data.get('bits_per_second', 0)
            mbps = bits_per_second / 1_000_000
            bws.append(mbps)
        
        return bws
    except:
        return []

def calculate_fairness_index(throughputs):
    """
    Jain's Fairness Index 계산
    FI = (Σ throughput)^2 / (N * Σ throughput^2)
    """
    if not throughputs or len(throughputs) == 0:
        return 0.0
    
    n = len(throughputs)
    sum_tp = sum(throughputs)
    sum_sq = sum(tp**2 for tp in throughputs)
    
    if sum_sq == 0:
        return 0.0
    
    fi = (sum_tp ** 2) / (n * sum_sq)
    return fi

def measure_reno_problem(net, duration=30):
    """
    Reno의 공정성 문제를 측정
    """
    receiver = net.get('receiver')
    senders = [net.get(f'h{i}') for i in range(1, 11)]
    
    # iperf3 서버 시작
    receiver.cmd('pkill -f "iperf3 -s" || true')
    time.sleep(0.5)
    receiver.cmd('iperf3 -s -p 5201 -D 2>/dev/null')
    time.sleep(2)
    
    # 임시 파일 정리
    os.system('rm -f /tmp/iperf_flow*.json')
    
    info("\n" + "="*70)
    info("TCP Reno 문제 실험 시작")
    info("="*70 + "\n")
    
    # 모든 송신자에서 동시에 iperf3 클라이언트 시작
    threads = []
    for i, sender in enumerate(senders):
        t = threading.Thread(
            target=run_iperf_test,
            args=(sender, receiver.IP(), i+1, duration)
        )
        threads.append(t)
        t.start()
    
    # 파일이 생성될 때까지 대기
    time.sleep(3)
    
    # 실시간 모니터링
    results = {
        'time': [],
        'fairness_index': [],
        'link_utilization': [],
        'max_flow': [],
        'min_flow': [],
        'avg_flow': []
    }
    
    start_time = time.time()
    measurement_interval = 3  # 3초마다 측정
    
    while time.time() - start_time < duration + 5:
        elapsed = int(time.time() - start_time)
        
        # 모든 플로우의 최신 처리량 수집
        all_throughputs = []
        
        for i in range(1, 11):
            bws = parse_iperf_json_realtime(f'/tmp/iperf_flow{i}.json')
            if bws:
                # 마지막 측정값 사용
                all_throughputs.append(bws[-1])
            else:
                all_throughputs.append(0)
        
        # 메트릭 계산
        if any(tp > 0 for tp in all_throughputs):
            fi = calculate_fairness_index(all_throughputs)
            total_tp = sum(all_throughputs)
            link_util = (total_tp / 1.0) * 100  # 1Mbps 기준
            max_tp = max(all_throughputs)
            min_tp = min(t for t in all_throughputs if t > 0) if any(t > 0 for t in all_throughputs) else 0
            avg_tp = total_tp / len(all_throughputs)
            
            results['time'].append(elapsed)
            results['fairness_index'].append(fi)
            results['link_utilization'].append(link_util)
            results['max_flow'].append(max_tp)
            results['min_flow'].append(min_tp)
            results['avg_flow'].append(avg_tp)
            
            info(f"[{elapsed:3d}s] FI={fi:.3f}, LinkUtil={link_util:.1f}%, "
                 f"AvgFlow={avg_tp:.3f}Mbps, "
                 f"MaxFlow={max_tp:.3f}Mbps, MinFlow={min_tp:.3f}Mbps\n")
        
        time.sleep(measurement_interval)
    
    # 모든 스레드 대기
    for t in threads:
        t.join(timeout=5)
    
    # 정리
    receiver.cmd('pkill -f iperf3')
    for sender in senders:
        sender.cmd('pkill -f iperf3')
    
    return results

def main():
    setLogLevel('info')
    
    topo = MultiFlowTopology()
    net = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    
    net.start()
    
    try:
        info("\n" + "="*70)
        info("TCP Reno 공정성 문제 실험")
        info("="*70)
        info("\n토폴로지:")
        info("  - 송신자: 10개 호스트")
        info("  - 수신자: 1개 호스트")
        info("  - 병목 링크: 1Mbps, 100ms 지연, 1% 손실\n")
        
        results = measure_reno_problem(net, duration=30)
        
        # 결과 분석
        info("\n" + "="*70)
        info("실험 결과 분석")
        info("="*70 + "\n")
        
        if results['fairness_index']:
            avg_fi = sum(results['fairness_index']) / len(results['fairness_index'])
            avg_util = sum(results['link_utilization']) / len(results['link_utilization'])
            avg_max = sum(results['max_flow']) / len(results['max_flow'])
            avg_min = sum(results['min_flow']) / len(results['min_flow'])
            
            info(f"평균 Fairness Index: {avg_fi:.3f}\n")
            info(f"평균 링크 활용도: {avg_util:.1f}%\n")
            info(f"평균 최대 플로우: {avg_max:.3f}Mbps\n")
            info(f"평균 최소 플로우: {avg_min:.3f}Mbps\n")
            
            if avg_min > 0:
                ratio = avg_max / avg_min
                info(f"최대/최소 비율: {ratio:.1f}배\n")
            
            # 판정
            info("\n" + "="*70)
            if avg_fi < 0.5:
                info("⚠️  결론: Reno는 심각한 공정성 문제 보유 (FI < 0.5)")
                info(f"      일부 플로우가 {avg_max/avg_min:.1f}배 차이 발생")
            elif avg_fi < 0.8:
                info("⚠️  결론: Reno는 중간 정도의 공정성 문제 (0.5 ≤ FI < 0.8)")
            else:
                info("✓ Reno는 충분한 공정성 수준 (FI ≥ 0.8)")
            
            if avg_util < 80:
                info(f"      링크 활용도도 낮음: {avg_util:.1f}%")
            
            info("="*70 + "\n")
        else:
            info("⚠️  측정 실패: iperf3 데이터 수집 오류\n")
    
    finally:
        net.stop()

if __name__ == '__main__':
    main()
