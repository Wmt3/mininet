#include <linux/module.h>
#include <linux/kernel.h>
#include <net/tcp.h>

/* 기준 RTT: 20ms */
#define BASE_RTT_US 20000 

void tcp_balanced_init(struct sock *sk)
{
    tcp_sk(sk)->snd_ssthresh = TCP_INFINITE_SSTHRESH;
    tcp_sk(sk)->snd_cwnd = 1;
}

u32 tcp_balanced_ssthresh(struct sock *sk)
{
    const struct tcp_sock *tp = tcp_sk(sk);
    return max(tp->snd_cwnd >> 1U, 2U);
}

void tcp_balanced_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
    struct tcp_sock *tp = tcp_sk(sk);
    
    if (!tcp_is_cwnd_limited(sk))
        return;

    // Slow Start (기존과 동일)
    if (tp->snd_cwnd <= tp->snd_ssthresh) {
        acked = tcp_slow_start(tp, acked);
        if (!acked)
            return;
    } 
    // Congestion Avoidance (핵심 수정)
    else {
        u32 current_rtt_us = tp->srtt_us >> 3; 
        
        // 1. Fast Group (RTT < 20ms): 패널티 부여
        // 윈도우를 키우기 위한 목표치를 2배로 늘림 (성장 속도 1/2로 감소)
        if (current_rtt_us < BASE_RTT_US) {
            tcp_cong_avoid_ai(tp, tp->snd_cwnd * 2, acked);
        }
        // 2. Slow Group (RTT >= 20ms): 부스트 부여
        // ACK를 2배로 계산해줌 (성장 속도 2배 증가)
        // 너무 과하지 않게 딱 2배만 줍니다.
        else {
            tcp_cong_avoid_ai(tp, tp->snd_cwnd, acked * 2);
        }
    }
    tp->snd_cwnd = min(tp->snd_cwnd, tp->snd_cwnd_clamp);
}

u32 tcp_balanced_undo_cwnd(struct sock *sk)
{
    return tcp_sk(sk)->snd_cwnd;
}

static struct tcp_congestion_ops tcp_reno_balanced = {
    .init           = tcp_balanced_init,
    .ssthresh       = tcp_balanced_ssthresh,
    .cong_avoid     = tcp_balanced_cong_avoid,
    .undo_cwnd      = tcp_balanced_undo_cwnd,
    .owner          = THIS_MODULE,
    .name           = "reno_balanced", 
};

static int __init tcp_balanced_init_module(void)
{
    if (tcp_register_congestion_control(&tcp_reno_balanced))
        return -ENOBUFS;
    printk(KERN_INFO "TCP Reno Balanced Loaded\n");
    return 0;
}

static void __exit tcp_balanced_exit_module(void)
{
    tcp_unregister_congestion_control(&tcp_reno_balanced);
    printk(KERN_INFO "TCP Reno Balanced Unloaded\n");
}

module_init(tcp_balanced_init_module);
module_exit(tcp_balanced_exit_module);

MODULE_AUTHOR("Student");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Balanced Fair Reno");