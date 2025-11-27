#!/usr/bin/env python3
# measure_reno_debug.py
# iperf3 에러를 보기 위한 디버그 버전 (순차 실행)

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.node import OVSKernelSwitch
from mininet.log import setLogLevel
import time
import json


class BottleneckTopology(Topo):
    def build(self):
        # 송신자 그룹 h1~h5
        senders = [self.addHost(f'h{i}') for i in range(1, 6)]
        # 수신자 그룹 h6~h10
        receivers = [self.addHost(f'h{i+5}') for i in range(1, 6)]

        # 두 개의 스위치 + 중간 병목 링크 (1Mbps, RTT≈200ms)
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, failMode='standalone')
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch, failMode='standalone')

        # 송신자 ↔ s1: 10Mbps, 5ms
        for h in senders:
            self.addLink(h, s1, cls=TCLink, bw=10, delay='5ms', loss=0)

        # 병목: s1 ↔ s2: 1Mbps, 100ms
        self.addLink(s1, s2, cls=TCLink, bw=1, delay='100ms', loss=0)

        # s2 ↔ 수신자: 10Mbps, 5ms
        for h in receivers:
            self.addLink(s2, h, cls=TCLink, bw=10, delay='5ms', loss=0)


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

    print("\n[3] TCP Congestion Control 설정 (reno_custom)...")
    for i in range(1, 11):
        h = net.get(f'h{i}')
        h.cmd('sysctl -w net.ipv4.tcp_congestion_control=reno_custom > /dev/null')

    print("\n[4] iperf3 서버 시작 (h6~h10)...")
    ports = {}
    for i in range(6, 11):
        h = net.get(f'h{i}')
        port = 5200 + i
        ports[i] = port
        # 서버는 백그라운드
        cmd = f'iperf3 -s -p {port} > /tmp/iperf3_server_{i}.log 2>&1 &'
        print(f"  h{i}: {cmd}")
        h.cmd(cmd)

    time.sleep(2)
    print("  서버 시작 완료\n")

    duration = 5
    print(f"[5] iperf3 클라이언트 순차 실행 (t={duration}s)...\n")
    throughputs = []

    for i in range(1, 6):
        h_send = net.get(f'h{i}')
        recv_ip = f'10.0.0.{i + 5}'
        port = ports[i + 5]

        print(f"===== h{i} -> h{i+5} 테스트 (port {port}) =====")
        cmd = f'iperf3 -c {recv_ip} -p {port} -t {duration} -J'
        print(f"[CMD] {cmd}")
        result = h_send.cmd(cmd)

        print("\n[RAW OUTPUT]")
        print(result.strip()[:800])   # 너무 길면 앞부분만

        # JSON 파싱 시도
        try:
            data = json.loads(result)
            bw_mbps = data['end']['sum_received']['bits_per_second'] / 1e6
            throughputs.append(bw_mbps)
            print(f"\n[PARSED] Throughput = {bw_mbps:.3f} Mbps\n")
        except Exception as e:
            print(f"\n[PARSED] JSON 파싱 실패: {e}\n")

    print("\n[6] 요약 결과...")
    if throughputs:
        total_bw = sum(throughputs)
        link_capacity = 1.0
        link_util = (total_bw / (link_capacity * len(throughputs))) * 100  # 순차라서 N으로 나눔

        sum_bw = sum(throughputs)
        sum_sq = sum(x ** 2 for x in throughputs)
        fairness = (sum_bw ** 2) / (len(throughputs) * sum_sq) if sum_sq > 0 else 0

        print(f"  평균 Link Utilization (순차): {link_util:.2f}%")
        print(f"  Jain Fairness Index:       {fairness:.4f}")
        print(f"  개별 Throughput:           {[f'{x:.3f}' for x in throughputs]} Mbps")
    else:
        print("  유효한 throughput 데이터를 하나도 못 받음.")

    print("\n[7] 정리...")
    for i in range(6, 11):
        h = net.get(f'h{i}')
        h.cmd('pkill iperf3')

    net.stop()
    print("완료.\n")


if __name__ == '__main__':
    main()
