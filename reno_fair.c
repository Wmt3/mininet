#include <linux/module.h>
#include <linux/kernel.h>
#include <net/tcp.h>

#define BASE_RTT_US 10000 

void tcp_final_init(struct sock *sk)
{
    tcp_sk(sk)->snd_ssthresh = TCP_INFINITE_SSTHRESH;
    tcp_sk(sk)->snd_cwnd = 1;
}

u32 tcp_final_ssthresh(struct sock *sk)
{
    const struct tcp_sock *tp = tcp_sk(sk);
    return max(tp->snd_cwnd >> 1U, 2U);
}

void tcp_final_cong_avoid(struct sock *sk, u32 ack, u32 acked)
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
        
        /* [최종 수정] 복잡한 비율 계산 제거 */
        /* RTT가 10ms보다 크면(Slow 그룹이면), ACK를 2개 받은 셈 칩니다. */
        /* 이는 윈도우 증가 속도를 딱 2배로 만들어주지만, 폭발적인 Burst는 막아줍니다. */
        u32 rtt_ratio = 1;
        if (current_rtt_us > BASE_RTT_US) {
            rtt_ratio = 2; 
        }

        tcp_cong_avoid_ai(tp, tp->snd_cwnd, acked * rtt_ratio);
    }
    tp->snd_cwnd = min(tp->snd_cwnd, tp->snd_cwnd_clamp);
}

u32 tcp_final_undo_cwnd(struct sock *sk)
{
    return tcp_sk(sk)->snd_cwnd;
}

static struct tcp_congestion_ops tcp_reno_final = {
    .init           = tcp_final_init,
    .ssthresh       = tcp_final_ssthresh,
    .cong_avoid     = tcp_final_cong_avoid,
    .undo_cwnd      = tcp_final_undo_cwnd,
    .owner          = THIS_MODULE,
    .name           = "reno_final", 
};

static int __init tcp_final_init_module(void)
{
    if (tcp_register_congestion_control(&tcp_reno_final))
        return -ENOBUFS;
    printk(KERN_INFO "TCP Reno Final Loaded\n");
    return 0;
}

static void __exit tcp_final_exit_module(void)
{
    tcp_unregister_congestion_control(&tcp_reno_final);
    printk(KERN_INFO "TCP Reno Final Unloaded\n");
}

module_init(tcp_final_init_module);
module_exit(tcp_final_exit_module);

MODULE_AUTHOR("Student");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Final Stable Fair Reno");