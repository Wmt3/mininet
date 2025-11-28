from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, Host
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.cli import CLI
import time
import re

class RTTUnfairnessTopo(Topo):
    def build(self):
        # 수신자 (Server)
        receiver = self.addHost('h_recv')
        s1 = self.addSwitch('s1')

        # [병목 링크] Server <-> Switch
        # 20Mbps 대역폭, 큐 크기 제한 (Bufferbloat 방지용)
        self.addLink(receiver, s1, cls=TCLink, bw=20, max_queue_size=100)

        # [그룹 A: 빠른 녀석들] h1~h3 (RTT ~10ms)
        for i in range(1, 4):
            sender = self.addHost(f'h{i}')
            # delay 5ms -> 왕복 10ms + @
            self.addLink(sender, s1, cls=TCLink, bw=100, delay='5ms')
        
        # [그룹 B: 느린 녀석들] h4~h6 (RTT ~200ms)
        for i in range(4, 7):
            sender = self.addHost(f'h{i}')
            # delay 100ms -> 왕복 200ms + @ (그룹 A보다 20배 느림)
            self.addLink(sender, s1, cls=TCLink, bw=100, delay='100ms')

def calculate_jains_index(throughputs):
    """
    Jain's Fairness Index 계산 함수
    Formula: (Sum x_i)^2 / (n * Sum (x_i^2))
    """
    n = len(throughputs)
    if n == 0:
        return 0.0

    sum_x = sum(throughputs)
    sum_x_sq = sum([x**2 for x in throughputs])

    if sum_x_sq == 0:
        return 0.0

    jains_index = (sum_x ** 2) / (n * sum_x_sq)
    return jains_index

def main():
    topo = RTTUnfairnessTopo()
    net = Mininet(topo=topo, host=Host, link=TCLink, autoSetMacs=True)
    net.start()

    h_recv = net.get('h_recv')
    senders = [net.get(f'h{i}') for i in range(1, 7)]

    info("=== 1. Starting iperf Server ===\n")
    h_recv.cmd('iperf -s &')

    info("=== 2. Starting 6 TCP Flows (Reno) ===\n")
    info("Group A (Fast RTT): h1, h2, h3\n")
    info("Group B (Slow RTT): h4, h5, h6\n")
    
    # 모든 호스트가 동시에 전송 시작 (30초간)
    for sender in senders:
        sender.cmd(f'iperf -c {h_recv.IP()} -t 30 -i 10 > {sender.name}_result.txt &')

    info("=== Test Running (30s)... ===\n")
    
    # 실시간 모니터링을 위해 잠시 대기
    time.sleep(35)

    info("=== 3. Analyzing Fairness ===\n")
    
    # 결과 파싱 및 출력
    total_bw = 0
    group_a_bw = 0
    group_b_bw = 0
    
    # [추가] 개별 throughput을 저장할 리스트 (Jain's Index 계산용)
    throughput_list = []

    print(f"{'Host':<10} {'RTT Group':<15} {'Throughput (Mbps)':<20}")
    print("-" * 45)

    for i, sender in enumerate(senders):
        # iperf 결과 파일에서 마지막 줄의 대역폭(bitrate) 파싱
        try:
            # 간단하게 마지막 reported Bandwidth 라인을 가져옵니다.
            last_line = sender.cmd(f'tail -n 1 {sender.name}_result.txt').strip()
            
            # "Mbits/sec" 앞의 숫자 찾기
            match = re.search(r'([\d\.]+)\s+Mbits/sec', last_line)
            if match:
                bw = float(match.group(1))
            else:
                bw = 0.0 # 파싱 실패 시 0 처리
            
            # [추가] 리스트에 개별 대역폭 저장
            throughput_list.append(bw)

            total_bw += bw
            if i < 3: # h1~h3
                group_a_bw += bw
                group_str = "Fast (10ms)"
            else: # h4~h6
                group_b_bw += bw
                group_str = "Slow (200ms)"
            
            print(f"{sender.name:<10} {group_str:<15} {bw:.2f}")

        except Exception as e:
            print(f"Error parsing {sender.name}: {e}")
            throughput_list.append(0.0)

    print("-" * 45)
    print(f"Total Bandwidth: {total_bw:.2f} Mbps")
    
    if total_bw > 0:
        print(f"Group A (Fast) Share: {(group_a_bw/total_bw)*100:.1f}%")
        print(f"Group B (Slow) Share: {(group_b_bw/total_bw)*100:.1f}%")
    
    print("\n=== 4. Quantitative Fairness Measure ===")
    
    # [추가] Jain's Fairness Index 계산 및 출력
    j_index = calculate_jains_index(throughput_list)
    
    print(f"Throughput Distribution: {throughput_list}")
    print(f"Jain's Fairness Index: {j_index:.4f}")
    
    print("\n[Conclusion]")
    if j_index >= 0.9:
        print("=> Fairness Index is high (Close to 1.0). The network is FAIR.")
    elif j_index < 0.8:
         print(f"=> Fairness Index is LOW ({j_index:.4f}). The network is UNFAIR.")
         if group_a_bw > group_b_bw * 2:
             print("   (Fast RTT flows are dominating the link)")
    else:
        print("=> Fairness Index is moderate.")

    # Clean up
    h_recv.cmd('killall -9 iperf')
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    main()