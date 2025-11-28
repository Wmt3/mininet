#include <linux/module.h>
#include <linux/kernel.h>
#include <net/tcp.h>

/* 기준 RTT: 20ms (이것보다 빠르면 Fast 그룹으로 간주하고 페널티 부여) */
#define BASE_RTT_US 20000 
/* 페널티 강도: 10배 (빠른 놈들은 윈도우 키우기가 10배 힘들어짐) */
#define PENALTY_FACTOR 10

void tcp_penalty_init(struct sock *sk)
{
    tcp_sk(sk)->snd_ssthresh = TCP_INFINITE_SSTHRESH;
    tcp_sk(sk)->snd_cwnd = 1;
}

u32 tcp_penalty_ssthresh(struct sock *sk)
{
    const struct tcp_sock *tp = tcp_sk(sk);
    return max(tp->snd_cwnd >> 1U, 2U);
}

void tcp_penalty_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
    struct tcp_sock *tp = tcp_sk(sk);
    
    if (!tcp_is_cwnd_limited(sk))
        return;

    // Slow Start (기존 동일)
    if (tp->snd_cwnd <= tp->snd_ssthresh) {
        acked = tcp_slow_start(tp, acked);
        if (!acked)
            return;
    } 
    // Congestion Avoidance (수정됨)
    else {
        u32 current_rtt_us = tp->srtt_us >> 3; 
        
        /* [전략 수정] 느린 놈을 도와주는 게 아니라, 빠른 놈을 억제한다. */
        if (current_rtt_us < BASE_RTT_US) {
            /* Fast 그룹(RTT < 20ms)인 경우:
             * tcp_cong_avoid_ai의 두 번째 인자는 "목표 카운트(w)"입니다.
             * 이를 원래 윈도우 크기보다 PENALTY_FACTOR(10배)만큼 부풀립니다.
             * 결과적으로 ACK를 10배 더 많이 받아야 윈도우가 1 증가합니다.
             * -> 성장이 느려지지만, 패킷 Burst는 절대 발생하지 않음 (안전함).
             */
            tcp_cong_avoid_ai(tp, tp->snd_cwnd * PENALTY_FACTOR, acked);
        } else {
            /* Slow 그룹: 일반 Reno와 동일하게 동작 */
            tcp_cong_avoid_ai(tp, tp->snd_cwnd, acked);
        }
    }
    tp->snd_cwnd = min(tp->snd_cwnd, tp->snd_cwnd_clamp);
}

u32 tcp_penalty_undo_cwnd(struct sock *sk)
{
    return tcp_sk(sk)->snd_cwnd;
}

static struct tcp_congestion_ops tcp_reno_penalty = {
    .init           = tcp_penalty_init,
    .ssthresh       = tcp_penalty_ssthresh,
    .cong_avoid     = tcp_penalty_cong_avoid,
    .undo_cwnd      = tcp_penalty_undo_cwnd,
    .owner          = THIS_MODULE,
    .name           = "reno_penalty", 
};

static int __init tcp_penalty_init_module(void)
{
    if (tcp_register_congestion_control(&tcp_reno_penalty))
        return -ENOBUFS;
    printk(KERN_INFO "TCP Reno Penalty Loaded\n");
    return 0;
}

static void __exit tcp_penalty_exit_module(void)
{
    tcp_unregister_congestion_control(&tcp_reno_penalty);
    printk(KERN_INFO "TCP Reno Penalty Unloaded\n");
}

module_init(tcp_penalty_init_module);
module_exit(tcp_penalty_exit_module);

MODULE_AUTHOR("Student");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Penalty-based Fair Reno");