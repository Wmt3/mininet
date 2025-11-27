#!/usr/bin/env python3
# measure_baseline.py - Reno 기본 성능 측정 (10개 연결)

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.node import OVSKernelSwitch
from mininet.log import setLogLevel
import time, json, re


class TestTopo(Topo):
    def build(self):
        # 10개 송신자, 10개 수신자
        senders   = [self.addHost(f'h{i}')    for i in range(1, 11)]
        receivers = [self.addHost(f'h{i+10}') for i in range(1, 11)]
        
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, failMode='standalone')
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch, failMode='standalone')
        
        # 송신자 → s1: 고속
        for h in senders:
            self.addLink(h, s1, cls=TCLink, bw=10, delay='5ms')
        
        # 병목: s1 ↔ s2 (1Mbps, 100ms delay → RTT 200ms)
        self.addLink(s1, s2, cls=TCLink, bw=1, delay='100ms', max_queue_size=20)
        
        # s2 → 수신자: 고속
        for h in receivers:
            self.addLink(s2, h, cls=TCLink, bw=10, delay='5ms')


def measure_performance(cc_algo='reno', duration=20):
    """
    cc_algo: 'reno' 또는 'reno_custom'
    duration: iperf3 실행 시간(초)
    """
    topo = TestTopo()
    net  = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    net.start()
    
    # IP 설정
    for i in range(1, 21):
        h = net.get(f'h{i}')
        h.setIP(f'10.0.0.{i}/24', intf=f'h{i}-eth0')
    
    # TCP CC 설정
    for i in range(1, 21):
        net.get(f'h{i}').cmd(f'sysctl -w net.ipv4.tcp_congestion_control={cc_algo} > /dev/null')
    
    # iperf3 서버 시작 (h11~h20)
    for i in range(11, 21):
        port = 5000 + i
        net.get(f'h{i}').cmd(f'iperf3 -s -p {port} > /tmp/s{i}.log 2>&1 &')
    
    time.sleep(2)
    
    # iperf3 클라이언트 동시 실행 (h1~h10)
    logs = []
    for i in range(1, 11):
        dst  = f'10.0.0.{i+10}'
        port = 5000 + i + 10
        log  = f'/tmp/c{i}.json'
        logs.append((i, log))
        net.get(f'h{i}').cmd(f'iperf3 -c {dst} -p {port} -t {duration} -J > {log} 2>&1 &')
    
    # RTT 측정 (ping)
    rtt_logs = []
    for i in range(1, 11):
        dst = f'10.0.0.{i+10}'
        log = f'/tmp/ping{i}.txt'
        rtt_logs.append((i, log))
        net.get(f'h{i}').cmd(f'ping -c 15 -i 1 {dst} > {log} 2>&1 &')
    
    time.sleep(duration + 3)
    
    # Throughput 수집
    throughputs = []
    for i, log in logs:
        out = net.get(f'h{i}').cmd(f'cat {log}')
        try:
            data = json.loads(out)
            bw_mbps = data['end']['sum_received']['bits_per_second'] / 1e6
            throughputs.append(bw_mbps)
        except:
            pass
    
    # RTT 수집
    rtts = []
    for i, log in rtt_logs:
        out = net.get(f'h{i}').cmd(f'cat {log}')
        # rtt min/avg/max/mdev 라인 파싱
        for line in out.splitlines():
            if 'rtt min/avg/max' in line:
                parts = line.split('=')[1].split('/')
                avg_rtt = float(parts[1].strip().split()[0])
                rtts.append(avg_rtt)
                break
    
    net.stop()
    
    # 메트릭 계산
    result = {'cc': cc_algo}
    
    if throughputs:
        total = sum(throughputs)
        result['utilization'] = (total / 1.0) * 100  # 1Mbps 기준
        
        # Jain's Fairness Index
        n = len(throughputs)
        s = sum(throughputs)
        sq = sum(x*x for x in throughputs)
        result['fairness'] = (s*s) / (n*sq) if sq > 0 else 0
        
        result['throughputs'] = throughputs
        result['min_tput'] = min(throughputs)
        result['max_tput'] = max(throughputs)
    
    if rtts:
        result['rtt_avg'] = sum(rtts) / len(rtts)
        result['rtt_min'] = min(rtts)
        result['rtt_max'] = max(rtts)
    
    return result


if __name__ == '__main__':
    setLogLevel('info')
    
    print("\n===== Reno Baseline 측정 =====\n")
    baseline = measure_performance(cc_algo='reno', duration=20)
    
    print(f"\n[결과]")
    print(f"Link Utilization:  {baseline.get('utilization', 0):.2f}%")
    print(f"Fairness Index:    {baseline.get('fairness', 0):.4f}")
    print(f"Throughput 범위:   {baseline.get('min_tput', 0):.3f} ~ {baseline.get('max_tput', 0):.3f} Mbps")
    print(f"평균 RTT:          {baseline.get('rtt_avg', 0):.1f} ms")
    print(f"RTT 범위:          {baseline.get('rtt_min', 0):.1f} ~ {baseline.get('rtt_max', 0):.1f} ms")
    print(f"\n개별 throughput: {[f'{x:.3f}' for x in baseline.get('throughputs', [])]}")
