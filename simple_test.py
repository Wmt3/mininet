#!/usr/bin/env python3
# measure_fixed_server_based.py - server sum_received 기준으로 측정 (util/fairness 정확화)

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

        # access 링크
        for h in senders:
            self.addLink(h, s1, cls=TCLink, bw=10, delay='5ms')

        # bottleneck: 1Mbps, 편도 100ms(왕복 ~200ms), 큐 제한
        self.addLink(s1, s2, cls=TCLink, bw=1, delay='100ms', max_queue_size=50)

        for h in receivers:
            self.addLink(s2, h, cls=TCLink, bw=10, delay='5ms')


def wait_for_nonempty_file(host, path, timeout_sec=5.0, interval=0.1):
    """host(cmd 실행 주체)의 path 파일이 생성되어 0보다 커질 때까지 대기"""
    waited = 0.0
    while waited < timeout_sec:
        # stat -c %s 가 실패하면 빈 문자열 -> int 변환 대비
        size_str = host.cmd(f'stat -c %s {path} 2>/dev/null').strip()
        try:
            size = int(size_str)
        except:
            size = 0
        if size > 0:
            return True, size
        time.sleep(interval)
        waited += interval
    return False, 0


def measure_performance(cc_algo='reno', duration=30):
    topo = TestTopo()
    net  = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    net.start()

    # IP 설정
    for i in range(1, 21):
        h = net.get(f'h{i}')
        h.setIP(f'10.0.0.{i}/24', intf=f'h{i}-eth0')

    # CC 알고리즘 통일
    for i in range(1, 21):
        net.get(f'h{i}').cmd(
            f'sysctl -w net.ipv4.tcp_congestion_control={cc_algo} > /dev/null'
        )

    # ----- iperf3 서버: JSON을 stdout으로 파일에 리다이렉션 -----
    # 참고: -J는 JSON을 stdout으로 출력, --forceflush로 즉시 플러시 가능[web:27][web:24]
    server_logs = {}
    for i in range(11, 21):
        port = 5000 + i
        logp = f'/tmp/s{i}.json'
        server_logs[i] = logp
        # -1: 단일 테스트 후 종료, -J: JSON, stdout을 파일로 보냄
        net.get(f'h{i}').cmd(
            f'iperf3 -s -p {port} -1 -J > {logp} 2>&1 &'
            # 필요 시 강제 플러시
            # f'iperf3 -s -p {port} -1 -J --forceflush > {logp} 2>&1 &'
        )

    time.sleep(2)

    # ----- iperf3 클라이언트 시작 -----
    for i in range(1, 11):
        dst  = f'10.0.0.{i+10}'
        port = 5000 + i + 10
        # 클라 로그는 디버그용
        clog = f'/tmp/c{i}.json'
        net.get(f'h{i}').cmd(
            f'iperf3 -c {dst} -p {port} -t {duration} -i 1 -J > {clog} 2>&1 &'
        )

    # ----- RTT 측정 (동시에 핑) -----
    rtt_logs = []
    for i in range(1, 11):
        dst = f'10.0.0.{i+10}'
        plog = f'/tmp/ping{i}.txt'
        rtt_logs.append((i, plog))
        net.get(f'h{i}').cmd(f'ping -c 20 -i 1.5 {dst} > {plog} 2>&1 &')

    # 대기
    time.sleep(duration + 5)

    # ----- 서버 JSON 파싱: sum_received 기반 goodput -----
    throughputs = []
    for idx in range(1, 11):
        recv_id = idx + 10
        logp = server_logs[recv_id]
        ok, size = wait_for_nonempty_file(net.get(f'h{recv_id}'), logp, timeout_sec=5.0)
        out = net.get(f'h{recv_id}').cmd(f'cat {logp}')
        try:
            data = json.loads(out)
            bw_mbps = data['end']['sum_received']['bits_per_second'] / 1e6
            throughputs.append(bw_mbps)
            print(f"h{idx} -> h{recv_id}: {bw_mbps:.3f} Mbps (server JSON size={size})")
        except Exception as e:
            print(f"h{idx} -> h{recv_id}: server JSON 파싱 실패 - {e} (size={size})")

    # ----- RTT 수집 -----
    rtts = []
    for i, plog in rtt_logs:
        out = net.get(f'h{i}').cmd(f'cat {plog}')
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
    print("\n===== Reno Baseline (10 flows, 1Mbps bottleneck, RTT ~200ms) =====\n")
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
