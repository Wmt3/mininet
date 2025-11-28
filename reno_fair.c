#include <linux/module.h>
#include <linux/kernel.h>
#include <net/tcp.h>

#define BASE_RTT_US 10000 
/* [수정] 상한선을 10 -> 4로 대폭 축소 (안전장치 강화) */
#define MAX_RATIO 4

void tcp_gentle_init(struct sock *sk)
{
    tcp_sk(sk)->snd_ssthresh = TCP_INFINITE_SSTHRESH;
    tcp_sk(sk)->snd_cwnd = 1;
}

u32 tcp_gentle_ssthresh(struct sock *sk)
{
    const struct tcp_sock *tp = tcp_sk(sk);
    return max(tp->snd_cwnd >> 1U, 2U);
}

void tcp_gentle_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
    struct tcp_sock *tp = tcp_sk(sk);
    
    if (!tcp_is_cwnd_limited(sk))
        return;

    if (tp->snd_cwnd <= tp->snd_ssthresh) {
        acked = tcp_slow_start(tp, acked);
        if (!acked)
            return;
    } else {
        u32 current_rtt_us = tp->srtt_us >> 3; 
        u32 rtt_ratio = 1;

        if (current_rtt_us > BASE_RTT_US) {
            u32 raw_ratio = current_rtt_us / BASE_RTT_US;
            
            /* [핵심 수정] 로그 함수 흉내내기 (매우 부드러운 증가)
             * 기존: ratio = raw_ratio / 2 (선형)
             * 수정: ratio = 1 + (raw_ratio / 6)
             * * 예시 (RTT 200ms, raw=20일 때):
             * 기존: 10배 (너무 셈)
             * 수정: 1 + (20/6) = 1 + 3 = 4배 (적절)
             */
            rtt_ratio = 1 + (raw_ratio / 6);

            // 상한선 적용 (Max 4)
            if (rtt_ratio > MAX_RATIO) {
                rtt_ratio = MAX_RATIO;
            }
        }

        tcp_cong_avoid_ai(tp, tp->snd_cwnd, acked * rtt_ratio);
    }
    tp->snd_cwnd = min(tp->snd_cwnd, tp->snd_cwnd_clamp);
}

u32 tcp_gentle_undo_cwnd(struct sock *sk)
{
    return tcp_sk(sk)->snd_cwnd;
}

static struct tcp_congestion_ops tcp_reno_gentle = {
    .init           = tcp_gentle_init,
    .ssthresh       = tcp_gentle_ssthresh,
    .cong_avoid     = tcp_gentle_cong_avoid,
    .undo_cwnd      = tcp_gentle_undo_cwnd,
    .owner          = THIS_MODULE,
    .name           = "reno_gentle", 
};

static int __init tcp_gentle_init_module(void)
{
    if (tcp_register_congestion_control(&tcp_reno_gentle))
        return -ENOBUFS;
    printk(KERN_INFO "TCP Reno Gentle Loaded\n");
    return 0;
}

static void __exit tcp_gentle_exit_module(void)
{
    tcp_unregister_congestion_control(&tcp_reno_gentle);
    printk(KERN_INFO "TCP Reno Gentle Unloaded\n");
}

module_init(tcp_gentle_init_module);
module_exit(tcp_gentle_exit_module);

MODULE_AUTHOR("Student");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Gentle RTT-Fair TCP Reno");