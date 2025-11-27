#!/usr/bin/env python3
# verify_setup.py

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.node import OVSKernelSwitch
from mininet.log import setLogLevel
import time

class TestTopo(Topo):
    def build(self):
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, failMode='standalone')
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch, failMode='standalone')
        
        self.addLink(h1, s1, cls=TCLink, bw=10, delay='5ms')
        self.addLink(s1, s2, cls=TCLink, bw=1, delay='100ms')  # 병목
        self.addLink(s2, h2, cls=TCLink, bw=10, delay='5ms')

if __name__ == '__main__':
    setLogLevel('info')
    topo = TestTopo()
    net = Mininet(topo=topo, link=TCLink, autoSetMacs=True)
    net.start()
    
    h1 = net.get('h1')
    h2 = net.get('h2')
    h1.setIP('10.0.0.1/24')
    h2.setIP('10.0.0.2/24')
    
    print("\n[TEST] ping으로 RTT 확인")
    result = h1.cmd('ping -c 5 10.0.0.2')
    print(result)
    
    print("\n[TEST] iperf3 단일 플로우")
    h2.cmd('iperf3 -s &')
    time.sleep(2)
    result = h1.cmd('iperf3 -c 10.0.0.2 -t 10')
    print(result)
    
    print("\n[TEST] tc 설정 확인")
    print(h1.cmd('tc -s qdisc show dev h1-eth0'))
    print(net.get('s1').cmd('tc -s qdisc show'))
    
    net.stop()
