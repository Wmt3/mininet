#!/usr/bin/env python3
# 6-flow MSS 편향 실험: Reno의 MSS-bias로 인한 공정성 저하/지연 증가 관측
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.node import OVSKernelSwitch
from mininet.log import setLogLevel
import time, json

BOTTLENECK_Mbps = 2.0      # s1-s2 용량
ONEWAY_DELAY = '50ms'      # 편도 지연(왕복 ~100ms)
DURATION = 30              # 초

class MssBiasTopo(Topo):
    def build(self):
        # 6 senders: h1..h6, 1 server: h7
        for i in range(1, 8):
            self.addHost(f'h{i}')
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, failMode='standalone')
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch, failMode='standalone')
        # 접속 링크는 충분히 여유
        for i in range(1, 7):
            self.addLink(f'h{i}', s1, cls=TCLink, bw=50, delay='5ms')
        self.addLink(s2, 'h7', cls=TCLink, bw=50, delay='5ms')
        # 병목 링크: 2 Mbps, 편도 50ms, 큐 제한
        self.addLink(s1, s2, cls=TCLink, bw=BOTTLENECK_Mbps, delay=ONEWAY_DELAY, max_queue_size=50)

def wait_nonempty(host, path, timeout=5.0, interval=0.1):
    waited = 0.0
    while waited < timeout:
        size_str = host.cmd(f'stat -c %s {path} 2>/dev/null').strip()
        try: size = int(size_str)
        except: size = 0
        if size > 0: return True, size
        time.sleep(interval); waited += interval
    return False, 0

def measure(cc_algo='reno', duration=DURATION):
    topo = MssBiasTopo()
    net  = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    net.start()

    # IP
    for i in range(1, 8):
        h = net.get(f'h{i}')
        h.setIP(f'10.0.0.{i}/24', intf=f'h{i}-eth0')

    # CC
    for i in range(1, 8):
        net.get(f'h{i}').cmd(f'sysctl -w net.ipv4.tcp_congestion_control={cc_algo} > /dev/null')

    # MSS 편향 유도: h1~h3 MTU 1500(기본), h4~h6 MTU 600
    for i in range(4, 7):
        net.get(f'h{i}').cmd('ip link set dev h%d-eth0 mtu 600' % i)

    # iperf3 서버(하나의 호스트 h7, 서로 다른 포트)
    ports = [5201, 5202, 5203, 5204, 5205, 5206]
    for p in ports:
        net.get('h7').cmd(f'iperf3 -s -p {p} -1 -J > /tmp/s{p}.json 2>&1 &')

    time.sleep(2)

    # 클라이언트 시작
    for i, p in enumerate(ports, start=1):
        net.get(f'h{i}').cmd(f'iperf3 -c 10.0.0.7 -p {p} -t {duration} -i 1 -J > /tmp/c{i}.json 2>&1 &')

    # RTT 측정
    for i in range(1, 7):
        net.get(f'h{i}').cmd(f'ping -c 20 -i 1.5 10.0.0.7 > /tmp/p{i}.txt 2>&1 &')

    time.sleep(duration + 5)

    # 서버 JSON sum_received 기반 goodput 수집
    tputs = []
    for p in ports:
        ok, size = wait_nonempty(net.get('h7'), f'/tmp/s{p}.json', timeout=5.0)
        out = net.get('h7').cmd(f'cat /tmp/s{p}.json')
        try:
            data = json.loads(out)
            bps = data['end']['sum_received']['bits_per_second']
            tputs.append(bps / 1e6)
        except Exception as e:
            print(f'parse fail port {p}: {e} (size={size})')

    # RTT 파싱
    rtts = []
    for i in range(1, 7):
        out = net.get(f'h{i}').cmd(f'grep "rtt min/avg/max" /tmp/p{i}.txt || true')
        if '=' in out:
            try:
                parts = out.split('=')[1].split('/')
                rtts.append(float(parts[1].strip().split()[0]))
            except: pass

    net.stop()

    # 메트릭
    res = {'cc': cc_algo}
    if tputs:
        total = sum(tputs)
        n = len(tputs)
        s = sum(tputs)
        sq = sum(x*x for x in tputs)
        res['utilization'] = (total / BOTTLENECK_Mbps) * 100.0     # goodput 기준
        res['fairness']    = (s*s)/(n*sq) if sq>0 else 0.0          # Jain index
        res['throughputs'] = tputs
        res['avg_tput']    = total/n
        res['min_tput']    = min(tputs); res['max_tput']=max(tputs)
    if rtts:
        res['rtt_avg']=sum(rtts)/len(rtts); res['rtt_min']=min(rtts); res['rtt_max']=max(rtts)
    return res

if __name__ == '__main__':
    setLogLevel('info')
    print('\n===== Reno with 6 flows (MSS-heterogeneous) =====\n')
    R = measure('reno', DURATION)
    print('\n==============================')
    print('[결과 요약]')
    print('==============================')
    print(f"CC: {R.get('cc')}")
    print(f"Link Utilization: {R.get('utilization',0):.2f}%")
    print(f"Fairness (Jain): {R.get('fairness',0):.4f}")
    print(f"평균 Throughput: {R.get('avg_tput',0):.4f} Mbps")
    print(f"Throughput 범위: {R.get('min_tput',0):.4f} ~ {R.get('max_tput',0):.4f} Mbps")
    print(f"평균 RTT: {R.get('rtt_avg',0):.1f} ms "
          f"(min {R.get('rtt_min',0):.1f}, max {R.get('rtt_max',0):.1f})")
    print('\n개별 throughput (Mbps):')
    for i, tp in enumerate(R.get('throughputs',[]), 1):
        print(f'  flow{i}: {tp:.4f}')
    print('==============================\n')
