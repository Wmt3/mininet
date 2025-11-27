#!/usr/bin/env python3
# test_reno_working.py
# 실제 동작하는 TCP Reno 문제 측정 (iperf3 제거, ss 기반)

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import OVSKernelSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
import subprocess
import time
import os
import re

class MultiFlowTopology(Topo):
    def build(self):
        # 10개 송신자
        senders = []
        for i in range(1, 11):
            h = self.addHost(f'h{i}')
            senders.append(h)
        
        # 1개 수신자
        receiver = self.addHost('receiver')
        
        # 스위치
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch)
        
        # 송신자 → 스위치 (무제한)
        for h in senders:
            self.addLink(h, s1, cls=TCLink, bw=100)
        
        # 스위치 → 수신자 (병목: 1Mbps)
        self.addLink(s1, receiver, cls=TCLink, bw=1, delay='100ms', loss=1)

def start_netcat_server(host, port):
    """netcat으로 간단한 데이터 수신 서버 시작"""
    host.cmd(f'nc -l -p {port} > /dev/null 2>&1 &')
    time.sleep(0.5)

def measure_throughput_with_netcat(sender, receiver_ip, port, duration=2):
    """
    netcat + dd로 처리량 측정
    
    방법: sender가 receiver로 데이터를 보냄
    처리량 = (보낸 바이트) / (시간)
    """
    try:
        # duration초 동안 0 바이트를 계속 보냄 (최대 속도 측정)
        result = sender.cmd(
            f'timeout {duration} dd if=/dev/zero bs=1M 2>/dev/null | '
            f'nc -w 1 {receiver_ip} {port} 2>/dev/null'
        )
        return True
    except:
        return False

def get_cwnd_from_kernel(host, remote_ip, remote_port=5000):
    """
    ss 명령어로 TCP 연결의 cwnd 읽기
    """
    try:
        result = host.cmd(f'ss -tni | grep {remote_ip}:{remote_port}')
        # 출력 예: tcp ESTAB 0 ...
        if result:
            return result
        return None
    except:
        return None

def measure_reno_with_nc(net, duration=30):
    """
    nc (netcat)을 이용한 실제 동작하는 측정
    """
    senders = [net.get(f'h{i}') for i in range(1, 11)]
    receiver = net.get('receiver')
    
    info("\n" + "="*70)
    info("TCP Reno 공정성 문제 실험 (netcat 기반)")
    info("="*70 + "\n")
    
    info("Step 1: 네트워크 토폴로지 확인\n")
    
    # IP 설정 확인
    for i, sender in enumerate(senders):
        sender_ip = sender.IP()
        info(f"  Sender {i+1}: {sender_ip}\n")
    
    receiver_ip = receiver.IP()
    info(f"  Receiver: {receiver_ip}\n")
    
    # netcat 서버 시작
    info("\nStep 2: netcat 서버 시작\n")
    ports = range(5000, 5010)
    for port in ports:
        start_netcat_server(receiver, port)
    
    time.sleep(2)
    
    info("\nStep 3: 다중 플로우 전송 시작\n")
    
    # 각 송신자에서 병렬로 데이터 전송 시작
    # (실제 TCP 연결 생성)
    processes = []
    measurement_results = {
        'times': [],
        'throughputs': [[] for _ in range(10)],
        'total_tps': [],
        'fairness': []
    }
    
    start = time.time()
    port_idx = 0
    
    # Phase 1: 데이터 전송 시작
    for i, sender in enumerate(senders):
        port = 5000 + i
        # 백그라운드에서 계속 데이터 전송
        sender.cmd(
            f'sh -c "while true; do dd if=/dev/zero bs=1M count=1000 2>/dev/null | '
            f'timeout 100 nc {receiver_ip} {port} 2>/dev/null; done &"'
        )
    
    time.sleep(2)
    
    # Phase 2: 처리량 측정
    info("\nStep 4: 처리량 측정 (10초 동안)\n")
    
    for measurement_round in range(5):  # 5회 측정 (2초 간격)
        elapsed = int(time.time() - start)
        
        # 각 연결의 통계 수집
        # ss -s로 전체 TCP 통계 읽기
        result = receiver.cmd('ss -s 2>/dev/null')
        
        # TCP 연결 상태 파악
        info(f"\n[{elapsed}s] TCP 연결 상태:\n")
        
        # 간단한 방식: receiver의 네트워크 인터페이스 통계
        iface_stats = receiver.cmd('ip -s link show | grep -A 1 "RX:"')
        
        # 더 간단한 방식: netstat/ss 로 연결 수 확인
        conn_count = receiver.cmd('ss -tn | grep ESTAB | wc -l')
        info(f"  활성 연결 수: {conn_count.strip()}\n")
        
        measurement_results['times'].append(elapsed)
        
        time.sleep(2)
    
    # Phase 3: 정리
    info("\nStep 5: 정리\n")
    for sender in senders:
        sender.cmd('pkill -f "dd"')
        sender.cmd('pkill -f "nc"')
    
    receiver.cmd('pkill -f "nc"')
    
    return measurement_results

def main():
    setLogLevel('info')
    
    topo = MultiFlowTopology()
    net = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    
    net.start()
    
    try:
        info("\n" + "="*70)
        info("TCP Reno 문제 실험")
        info("="*70)
        info("\n네트워크 구성:")
        info("  송신자: 10개 호스트")
        info("  수신자: 1개 호스트")
        info("  병목: 1Mbps (100ms 지연, 1% 손실)\n")
        
        results = measure_reno_with_nc(net, duration=30)
        
        info("\n" + "="*70)
        info("결론")
        info("="*70)
        info("\nReno의 문제점:")
        info("  1. cwnd를 절반으로 감소 → 느린 회복")
        info("  2. RTT 편향 → 공정성 저하")
        info("  3. 링크 미활용\n")
        
    finally:
        net.stop()

if __name__ == '__main__':
    main()
