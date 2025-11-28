#include <linux/module.h>
#include <linux/kernel.h>
#include <net/tcp.h>

/* 기준 RTT: 10ms (10000us) */
#define BASE_RTT_US 10000 
/* [추가] 가중치 상한선: 과도한 Burst 방지 */
#define MAX_RATIO 10

void tcp_tuned_init(struct sock *sk)
{
    tcp_sk(sk)->snd_ssthresh = TCP_INFINITE_SSTHRESH;
    tcp_sk(sk)->snd_cwnd = 1;
}

u32 tcp_tuned_ssthresh(struct sock *sk)
{
    const struct tcp_sock *tp = tcp_sk(sk);
    return max(tp->snd_cwnd >> 1U, 2U);
}

void tcp_tuned_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
    struct tcp_sock *tp = tcp_sk(sk);
    
    if (!tcp_is_cwnd_limited(sk))
        return;

    // Slow Start 구간 (기존과 동일)
    if (tp->snd_cwnd <= tp->snd_ssthresh) {
        acked = tcp_slow_start(tp, acked);
        if (!acked)
            return;
    } 
    // Congestion Avoidance 구간 (수정됨)
    else {
        u32 current_rtt_us = tp->srtt_us >> 3; 
        u32 rtt_ratio = 1;

        if (current_rtt_us > BASE_RTT_US) {
            // [수정 1] 비율 계산 (Raw Ratio)
            u32 raw_ratio = current_rtt_us / BASE_RTT_US;
            
            // [수정 2] Damping (감쇄): 강도를 절반으로 줄임
            // (20배 차이나면 -> 10.5배 정도로 보정)
            rtt_ratio = (raw_ratio + 1) / 2;

            // [수정 3] Capping (상한선): 최대 10배를 넘지 않도록 제한
            if (rtt_ratio > MAX_RATIO) {
                rtt_ratio = MAX_RATIO;
            }
        }

        // 보정된 가중치를 적용하여 윈도우 증가
        tcp_cong_avoid_ai(tp, tp->snd_cwnd, acked * rtt_ratio);
    }

    tp->snd_cwnd = min(tp->snd_cwnd, tp->snd_cwnd_clamp);
}

u32 tcp_tuned_undo_cwnd(struct sock *sk)
{
    return tcp_sk(sk)->snd_cwnd;
}

static struct tcp_congestion_ops tcp_reno_tuned = {
    .init           = tcp_tuned_init,
    .ssthresh       = tcp_tuned_ssthresh,
    .cong_avoid     = tcp_tuned_cong_avoid,
    .undo_cwnd      = tcp_tuned_undo_cwnd,

    .owner          = THIS_MODULE,
    .name           = "reno_tuned", // 이름 변경
};

static int __init tcp_tuned_module_init(void)
{
    if (tcp_register_congestion_control(&tcp_reno_tuned))
        return -ENOBUFS;
    printk(KERN_INFO "TCP Reno Tuned (Damped) Loaded\n");
    return 0;
}

static void __exit tcp_tuned_module_exit(void)
{
    tcp_unregister_congestion_control(&tcp_reno_tuned);
    printk(KERN_INFO "TCP Reno Tuned (Damped) Unloaded\n");
}

module_init(tcp_tuned_module_init);
module_exit(tcp_tuned_module_exit);

MODULE_AUTHOR("Student");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Tuned RTT-Fair TCP Reno");