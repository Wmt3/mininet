#!/usr/bin/env python3
# measure_fixed_server_based.py - server 통계(sum_received) 사용 버전

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.node import OVSKernelSwitch
from mininet.log import setLogLevel
import time, json

class TestTopo(Topo):
    def build(self):
        senders   = [self.addHost(f'h{i}')    for i in range(1, 11)]
        receivers = [self.addHost(f'h{i+10}') for i in range(1, 11)]

        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, failMode='standalone')
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch, failMode='standalone')

        # sender ↔ s1
        for h in senders:
            self.addLink(h, s1, cls=TCLink, bw=10, delay='5ms')

        # bottleneck 링크: 1Mbps, RTT≈200ms (편도 100ms)
        self.addLink(s1, s2, cls=TCLink, bw=1, delay='100ms', max_queue_size=50)

        # s2 ↔ receiver
        for h in receivers:
            self.addLink(s2, h, cls=TCLink, bw=10, delay='5ms')


def measure_performance(cc_algo='reno', duration=30):
    topo = TestTopo()
    net  = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    net.start()

    # IP 설정
    for i in range(1, 21):
        h = net.get(f'h{i}')
        h.setIP(f'10.0.0.{i}/24', intf=f'h{i}-eth0')

    # 모든 호스트에 동일한 CC 알고리즘 설정
    for i in range(1, 21):
        net.get(f'h{i}').cmd(
            f'sysctl -w net.ipv4.tcp_congestion_control={cc_algo} > /dev/null'
        )

    # ----- iperf3 서버 (receiver) : JSON 로그, sum_received 사용 -----
    for i in range(11, 21):
        port = 5000 + i
        # -1: 한 번 테스트 후 종료, -J: JSON, --logfile: 파일로 출력
        net.get(f'h{i}').cmd(
            f'iperf3 -s -p {port} -1 -J --logfile /tmp/s{i}.json > /dev/null 2>&1 &'
        )

    time.sleep(3)

    # ----- iperf3 클라이언트 (sender) -----
    for i in range(1, 11):
        dst  = f'10.0.0.{i+10}'
        port = 5000 + i + 10
        # 클라이언트 로그는 굳이 안 써도 되지만 디버깅용으로 남김
        log  = f'/tmp/c{i}.json'
        net.get(f'h{i}').cmd(
            f'iperf3 -c {dst} -p {port} -t {duration} -i 1 -J > {log} 2>&1 &'
        )

    # ----- RTT 측정 (ping) -----
    rtt_logs = []
    for i in range(1, 11):
        dst = f'10.0.0.{i+10}'
        log = f'/tmp/ping{i}.txt'
        rtt_logs.append((i, log))
        net.get(f'h{i}').cmd(
            f'ping -c 20 -i 1.5 {dst} > {log} 2>&1 &'
        )

    time.sleep(duration + 5)

    # ----- Throughput 수집: receiver JSON sum_received 기준 -----
    throughputs = []
    for idx in range(1, 11):
        recv_id = idx + 10
        log_path = f'/tmp/s{recv_id}.json'
        out = net.get(f'h{recv_id}').cmd(f'cat {log_path}')
        try:
            data = json.loads(out)
            bw_mbps = data['end']['sum_received']['bits_per_second'] / 1e6
            throughputs.append(bw_mbps)
            # 재전송 수는 sender 로그에서 보고 싶으면 별도로 파싱
            print(f"h{idx} -> h{recv_id}: {bw_mbps:.3f} Mbps")
        except Exception as e:
            print(f"h{idx} -> h{recv_id}: server JSON 파싱 실패 - {e}")

    # ----- RTT 수집 -----
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

    # ----- 메트릭 계산 -----
    result = {'cc': cc_algo}

    if throughputs:
        total = sum(throughputs)
        bottleneck_bw_mbps = 1.0  # s1-s2 링크 용량

        # 링크 이용률 (goodput 기준)
        result['utilization'] = (total / bottleneck_bw_mbps) * 100.0

        n = len(throughputs)
        s = sum(throughputs)
        sq = sum(x * x for x in throughputs)
        result['fairness'] = (s * s) / (n * sq) if sq > 0 else 0.0

        result['throughputs'] = throughputs
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

    print("\n===== Reno Baseline (10 flows, 1Mbps, RTT ~200ms) =====\n")
    result = measure_performance(cc_algo='reno', duration=30)

    print(f"\n{'='*50}")
    print(f"[결과 요약]")
    print(f"{'='*50}")
    print(f"Congestion Control:   {result.get('cc')}")
    print(f"Link Utilization:     {result.get('utilization', 0):.2f}%")
    print(f"Fairness Index:       {result.get('fairness', 0):.4f}")
    print(f"평균 Throughput:      {result.get('avg_tput', 0):.4f} Mbps")
    print(f"Throughput 범위:      {result.get('min_tput', 0):.4f} ~ {result.get('max_tput', 0):.4f} Mbps")
    print(f"평균 RTT:             {result.get('rtt_avg', 0):.1f} ms")
    print(f"RTT 범위:             {result.get('rtt_min', 0):.1f} ~ {result.get('rtt_max', 0):.1f} ms")
    print(f"\n개별 throughput (Mbps):")
    for i, tp in enumerate(result.get('throughputs', []), 1):
        print(f"  h{i} -> h{i+10}: {tp:.4f}")
    print(f"{'='*50}\n")
