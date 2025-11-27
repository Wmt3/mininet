#!/usr/bin/env python3
# measure_reno_concurrent.py
# 5개 TCP 플로우를 동시에 실행하여 Reno 성능 측정

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.node import OVSKernelSwitch
from mininet.log import setLogLevel
import time
import json
import re


class BottleneckTopology(Topo):
    def build(self):
        # 송신자 그룹 h1~h5
        senders = [self.addHost(f'h{i}') for i in range(1, 6)]
        # 수신자 그룹 h6~h10
        receivers = [self.addHost(f'h{i+5}') for i in range(1, 6)]

        # 두 개의 스위치 + 중간 병목 링크
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, failMode='standalone')  # 송신자쪽
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch, failMode='standalone')  # 수신자쪽

        # 송신자 → s1: 고속 링크 (혼잡 X)
        for h in senders:
            self.addLink(h, s1, cls=TCLink, bw=10, delay='5ms', loss=0)

        # ★ 병목 링크: s1 ↔ s2 (1Mbps, RTT≈200ms)
        self.addLink(s1, s2, cls=TCLink, bw=1, delay='100ms', loss=0)

        # s2 → 수신자: 고속 링크 (혼잡 X)
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
        port = 5200 + i      # 각 서버별 다른 포트
        ports[i] = port
        h.cmd(f'iperf3 -s -p {port} > /tmp/iperf3_server_{i}.log 2>&1 &')
    time.sleep(2)
    print("  서버 시작 완료")

    duration = 10  # 동시에 10초 동안 전송
    print(f"\n[5] iperf3 클라이언트 동시 실행 (t={duration}s)...")
    log_files = []

    # h1~h5에서 h6~h10으로 각각 하나씩 연결
    for i in range(1, 6):
        h_send = net.get(f'h{i}')
        recv_ip = f'10.0.0.{i + 5}'
        port = ports[i + 5]
        log = f'/tmp/iperf_client_{i}.json'
        log_files.append((i, log))

        print(f"  h{i} -> h{i+5} 시작 (port {port})...")
        # 백그라운드로 실행, 결과를 파일에 저장
        h_send.cmd(
            f'iperf3 -c {recv_ip} -p {port} -t {duration} -J > {log} 2>&1 &'
        )

    # 모든 클라이언트가 끝날 때까지 대기
    time.sleep(duration + 3)

    print("\n[6] 결과 수집/분석...")
    throughputs = []

    for i, log in log_files:
        h_send = net.get(f'h{i}')
        out = h_send.cmd(f'cat {log}')
        if not out.strip():
            print(f"  h{i}: 로그가 비어있음 (실행 실패 가능)")
            continue

        try:
            data = json.loads(out)
            bw_mbps = data['end']['sum_received']['bits_per_second'] / 1e6
            throughputs.append(bw_mbps)
            print(f"  h{i} -> h{i+5}: {bw_mbps:.3f} Mbps")
        except Exception as e:
            print(f"  h{i}: JSON 파싱 실패 ({e})")
            print(out[:200])

    if throughputs:
        total_bw = sum(throughputs)          # 동시에 10초 동안의 합계
        link_capacity = 1.0                  # 병목 링크 용량 (1 Mbps)
        link_util = (total_bw / link_capacity) * 100

        # Jain's Fairness Index
        sum_bw = sum(throughputs)
        sum_sq = sum(x ** 2 for x in throughputs)
        fairness = (sum_bw ** 2) / (len(throughputs) * sum_sq) if sum_sq > 0 else 0

        print("\n===== 성능 지표 (동시 실행) =====")
        print(f"Link Utilization: {link_util:.2f}%")
        print(f"Fairness Index:  {fairness:.4f}")
        print(f"개별 Throughput: {[f'{x:.3f}' for x in throughputs]} Mbps")

    print("\n[7] 정리...")
    for i in range(6, 11):
        h = net.get(f'h{i}')
        h.cmd('pkill iperf3')

    net.stop()


if __name__ == '__main__':
    main()
