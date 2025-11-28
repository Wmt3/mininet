// reno_abc.c - ABC(Appropriate Byte Counting) 구현
#include <linux/module.h>
#include <net/tcp.h>

void tcp_reno_abc_init(struct sock *sk)
{
    struct tcp_sock *tp = tcp_sk(sk);
    tp->snd_ssthresh = TCP_INFINITE_SSTHRESH;
    tp->snd_cwnd = 1;
}

u32 tcp_reno_abc_ssthresh(struct sock *sk)
{
    const struct tcp_sock *tp = tcp_sk(sk);
    return max(tp->snd_cwnd >> 1U, 2U);
}

void tcp_reno_abc_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
    struct tcp_sock *tp = tcp_sk(sk);
    
    printk(KERN_INFO "[ABC] cwnd=%d, ssthresh=%d, acked=%d bytes\n",
           tp->snd_cwnd, tp->snd_ssthresh, acked);
    
    if (!tcp_is_cwnd_limited(sk))
        return;
    
    if (tp->snd_cwnd <= tp->snd_ssthresh) {
        /* Slow start with ABC: bytes_acked 기준 증가 */
        /* acked는 이미 바이트 단위, MSS로 나눠서 패킷 수로 변환 */
        u32 delta = acked / tp->mss_cache;
        if (delta == 0)
            delta = 1;
        tp->snd_cwnd += delta;
        printk(KERN_INFO "[ABC] Slow start: cwnd increased by %d to %d\n",
               delta, tp->snd_cwnd);
    } else {
        /* Congestion avoidance with ABC: 바이트 기준 선형 증가 */
        /* cwnd += (bytes_acked / cwnd) 근사 */
        u32 w = tp->snd_cwnd;
        /* acked 바이트만큼 "크레딧" 누적, cwnd 크기만큼 쌓이면 +1 */
        if (acked >= w * tp->mss_cache) {
            tp->snd_cwnd += acked / (w * tp->mss_cache);
        } else {
            /* 표준 AI: 매 RTT당 1 MSS, 하지만 바이트 누적 방식 */
            tcp_cong_avoid_ai(tp, w, acked);
        }
        printk(KERN_INFO "[ABC] Congestion avoidance: cwnd=%d\n", tp->snd_cwnd);
    }
}

static struct tcp_congestion_ops tcp_reno_abc = {
    .init           = tcp_reno_abc_init,
    .ssthresh       = tcp_reno_abc_ssthresh,
    .cong_avoid     = tcp_reno_abc_cong_avoid,
    .owner          = THIS_MODULE,
    .name           = "reno_abc",
};

static int __init tcp_reno_abc_register(void)
{
    return tcp_register_congestion_control(&tcp_reno_abc);
}

static void __exit tcp_reno_abc_unregister(void)
{
    tcp_unregister_congestion_control(&tcp_reno_abc);
}

module_init(tcp_reno_abc_register);
module_exit(tcp_reno_abc_unregister);

MODULE_AUTHOR("Student");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("TCP Reno with ABC");
