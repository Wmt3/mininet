#!/usr/bin/env python3
# measure_correct.py - 올바른 throughput 측정

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.node import OVSKernelSwitch
from mininet.log import setLogLevel
import time, json, re


class TestTopo(Topo):
    def build(self):
        senders   = [self.addHost(f'h{i}')    for i in range(1, 11)]
        receivers = [self.addHost(f'h{i+10}') for i in range(1, 11)]
        
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, failMode='standalone')
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch, failMode='standalone')
        
        for h in senders:
            self.addLink(h, s1, cls=TCLink, bw=10, delay='5ms')
        
        # 병목: 1Mbps, delay 100ms, 큐 50개
        self.addLink(s1, s2, cls=TCLink, bw=1, delay='100ms', max_queue_size=50)
        
        for h in receivers:
            self.addLink(s2, h, cls=TCLink, bw=10, delay='5ms')


def measure_performance(cc_algo='reno', duration=30):
    topo = TestTopo()
    net  = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    net.start()
    
    for i in range(1, 21):
        h = net.get(f'h{i}')
        h.setIP(f'10.0.0.{i}/24', intf=f'h{i}-eth0')
    
    for i in range(1, 21):
        net.get(f'h{i}').cmd(f'sysctl -w net.ipv4.tcp_congestion_control={cc_algo} > /dev/null')
    
    # 서버
    for i in range(11, 21):
        port = 5000 + i
        net.get(f'h{i}').cmd(f'iperf3 -s -p {port} -1 > /tmp/s{i}.log 2>&1 &')  # -1: 한 번만
    
    time.sleep(3)
    
    # 클라이언트 동시 실행
    logs = []
    for i in range(1, 11):
        dst  = f'10.0.0.{i+10}'
        port = 5000 + i + 10
        log  = f'/tmp/c{i}.json'
        logs.append((i, log))
        net.get(f'h{i}').cmd(f'iperf3 -c {dst} -p {port} -t {duration} -J > {log} 2>&1 &')
    
    # RTT 측정
    rtt_logs = []
    for i in range(1, 11):
        dst = f'10.0.0.{i+10}'
        log = f'/tmp/ping{i}.txt'
        rtt_logs.append((i, log))
        net.get(f'h{i}').cmd(f'ping -c 20 -i 1.5 {dst} > {log} 2>&1 &')
    
    time.sleep(duration + 5)
    
    # Throughput 수집
    throughputs = []
    retransmits = []
    
    for i, log in logs:
        out = net.get(f'h{i}').cmd(f'cat {log}')
        try:
            data = json.loads(out)
            
            # ★ 핵심: receiver 통계 우선, 없으면 sender
            if 'sum_received' in data['end'] and data['end']['sum_received']['bits_per_second'] > 0:
                bw_mbps = data['end']['sum_received']['bits_per_second'] / 1e6
            else:
                bw_mbps = data['end']['sum_sent']['bits_per_second'] / 1e6
            
            throughputs.append(bw_mbps)
            retrans = data['end']['sum_sent'].get('retransmits', 0)
            retransmits.append(retrans)
            
            print(f"h{i}: {bw_mbps:.4f} Mbps (retrans: {retrans})")
            
        except Exception as e:
            print(f"h{i}: 파싱 실패 - {str(e)[:50]}")
    
    # RTT 수집
    rtts = []
    for i, log in rtt_logs:
        out = net.get(f'h{i}').cmd(f'cat {log}')
        for line in out.splitlines():
            if 'rtt min/avg/max' in line:
                try:
                    parts = line.split('=')[1].split('/')
                    avg_rtt = float(parts[1].strip().split()[0])
                    rtts.append(avg_rtt)
                except:
                    pass
                break
    
    net.stop()
    
    # 메트릭
    result = {'cc': cc_algo}
    
    if throughputs:
        total = sum(throughputs)
        result['utilization'] = (total / 1.0) * 100  # 1Mbps 기준
        
        n = len(throughputs)
        s = sum(throughputs)
        sq = sum(x*x for x in throughputs)
        result['fairness'] = (s*s) / (n*sq) if sq > 0 else 0
        
        result['throughputs'] = throughputs
        result['retransmits'] = retransmits
        result['total_retrans'] = sum(retransmits)
        result['min_tput'] = min(throughputs)
        result['max_tput'] = max(throughputs)
        result['avg_tput'] = total / n
    
    if rtts:
        result['rtt_avg'] = sum(rtts) / len(rtts)
        result['rtt_min'] = min(rtts)
        result['rtt_max'] = max(rtts)
    
    return result


if __name__ == '__main__':
    setLogLevel('info')
    
    print("\n" + "="*60)
    print("TCP Reno Baseline 측정 (10 flows, 1Mbps bottleneck)")
    print("="*60 + "\n")
    
    result = measure_performance(cc_algo='reno', duration=30)
    
    print(f"\n{'='*60}")
    print(f"[측정 결과]")
    print(f"{'='*60}")
    print(f"Congestion Control:      {result.get('cc')}")
    print(f"Link Utilization:        {result.get('utilization', 0):.2f}%")
    print(f"Fairness Index (Jain):   {result.get('fairness', 0):.4f}")
    print(f"")
    print(f"Throughput 통계:")
    print(f"  평균:                  {result.get('avg_tput', 0):.4f} Mbps")
    print(f"  최소 ~ 최대:           {result.get('min_tput', 0):.4f} ~ {result.get('max_tput', 0):.4f} Mbps")
    print(f"  비율 (최대/최소):      {result.get('max_tput', 1) / max(result.get('min_tput', 1), 0.001):.2f}x")
    print(f"")
    print(f"RTT 통계:")
    print(f"  평균:                  {result.get('rtt_avg', 0):.1f} ms")
    print(f"  최소 ~ 최대:           {result.get('rtt_min', 0):.1f} ~ {result.get('rtt_max', 0):.1f} ms")
    print(f"")
    print(f"재전송:")
    print(f"  총 재전송 횟수:        {result.get('total_retrans', 0)}")
    print(f"  플로우당 평균:         {result.get('total_retrans', 0) / len(result.get('throughputs', [1])):.1f}")
    print(f"{'='*60}\n")
