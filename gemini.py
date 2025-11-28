from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, Host
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.cli import CLI
import time
import re

# 병목 링크 대역폭 설정 (계산에 사용하기 위해 상수로 정의)
BOTTLENECK_BW = 10 

class RTTUnfairnessTopo(Topo):
    def build(self):
        # 수신자 (Server)
        receiver = self.addHost('h_recv')
        s1 = self.addSwitch('s1')

        # [병목 링크] Server <-> Switch
        # bw=10Mbps, 큐 크기 20 (Reno의 약점인 Bufferbloat 및 경쟁 유발)
        self.addLink(receiver, s1, cls=TCLink, bw=BOTTLENECK_BW, max_queue_size=20)

        # [그룹 A: 빠른 녀석들] h1~h3 (RTT ~10ms)
        for i in range(1, 4):
            sender = self.addHost(f'h{i}')
            self.addLink(sender, s1, cls=TCLink, bw=100, delay='5ms')
        
        # [그룹 B: 느린 녀석들] h4~h6 (RTT ~200ms)
        for i in range(4, 7):
            sender = self.addHost(f'h{i}')
            self.addLink(sender, s1, cls=TCLink, bw=100, delay='100ms')

def calculate_jains_index(throughputs):
    """ Jain's Fairness Index 계산 """
    n = len(throughputs)
    if n == 0: return 0.0
    sum_x = sum(throughputs)
    sum_x_sq = sum([x**2 for x in throughputs])
    if sum_x_sq == 0: return 0.0
    return (sum_x ** 2) / (n * sum_x_sq)

def main():
    topo = RTTUnfairnessTopo()
    net = Mininet(topo=topo, host=Host, link=TCLink, autoSetMacs=True)
    net.start()

    h_recv = net.get('h_recv')
    h1 = net.get('h1') # Latency 측정용 (Fast Group 대표)
    senders = [net.get(f'h{i}') for i in range(1, 7)]

    info("=== 1. Starting iperf Server ===\n")
    h_recv.cmd('iperf -s &')

    info("=== 2. Starting 6 TCP Flows (Generating Congestion) ===\n")
    # 모든 호스트가 동시에 전송 시작 (40초간)
    for sender in senders:
        sender.cmd(f'iperf -c {h_recv.IP()} -t 40 -i 10 > {sender.name}_result.txt &')

    info("=== Test Running... Waiting for congestion to build up (10s) ===\n")
    time.sleep(10)

    # [추가됨] Latency 측정
    info("=== 3. Measuring Latency (RTT) under Load ===\n")
    # 혼잡한 상황에서 h1이 h_recv에게 핑을 보냄
    ping_out = h1.cmd(f'ping -c 10 {h_recv.IP()}')
    
    # Ping 결과 파싱
    rtt_avg = 0.0
    try:
        # rtt min/avg/max/mdev = 20.1/25.2/30.5/1.2 ms 형태 파싱
        rtt_line = ping_out.splitlines()[-1]
        match = re.search(r'([\d\.]+)/([\d\.]+)/([\d\.]+)/([\d\.]+)', rtt_line)
        if match:
            rtt_avg = float(match.group(2)) # avg 값 추출
        info(f"Ping Output: {rtt_line}\n")
    except Exception as e:
        info(f"Ping Parse Error: {e}\n")

    info("=== Waiting for test to finish (Remaining time) ===\n")
    time.sleep(25) # 남은 시간 대기

    info("=== 4. Collecting Results ===\n")
    
    total_bw = 0
    throughput_list = []

    print(f"{'Host':<10} {'RTT Group':<15} {'Throughput (Mbps)':<20}")
    print("-" * 45)

    for i, sender in enumerate(senders):
        try:
            # iperf 결과 파일 파싱
            last_line = sender.cmd(f'tail -n 1 {sender.name}_result.txt').strip()
            match = re.search(r'([\d\.]+)\s+Mbits/sec', last_line)
            if match:
                bw = float(match.group(1))
            else:
                bw = 0.0
            
            throughput_list.append(bw)
            total_bw += bw
            
            group_str = "Fast (10ms)" if i < 3 else "Slow (200ms)"
            print(f"{sender.name:<10} {group_str:<15} {bw:.2f}")

        except Exception as e:
            print(f"Error parsing {sender.name}: {e}")
            throughput_list.append(0.0)

    print("-" * 45)

    # [분석 1] Fairness (공정성)
    j_index = calculate_jains_index(throughput_list)

    # [분석 2] Link Utilization (링크 효율)
    # 총 처리량 / 병목 대역폭 * 100
    utilization = (total_bw / BOTTLENECK_BW) * 100
    
    # [분석 3] Latency (지연 시간) - 위에서 측정한 rtt_avg 사용

    print("\n========= FINAL ANALYSIS REPORT =========")
    print(f"[1] Link Utilization: {utilization:.2f}%")
    print(f"    - Target: Close to 100% (approx 90-95% is realistic for TCP)")
    print(f"    - Current Total Throughput: {total_bw:.2f} Mbps / {BOTTLENECK_BW} Mbps")
    
    print(f"\n[2] Latency (Bufferbloat): {rtt_avg:.2f} ms")
    print(f"    - Base RTT: approx 10ms")
    print(f"    - If this value is high (>100ms), Reno is causing Bufferbloat.")
    
    print(f"\n[3] Fairness (Jain's Index): {j_index:.4f}")
    if j_index < 0.8:
        print("    - Result: UNFAIR. Fast RTT flows are likely dominating.")
    else:
        print("    - Result: FAIR.")
    
    print("=========================================")

    # Clean up
    h_recv.cmd('killall -9 iperf')
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    main()