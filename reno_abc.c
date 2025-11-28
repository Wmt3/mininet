// reno_abc.c - ABC(Appropriate Byte Counting) 제대로 구현
#include <linux/module.h>
#include <linux/kernel.h>
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
    
    if (!tcp_is_cwnd_limited(sk))
        return;
    
    /* Slow Start with ABC */
    if (tp->snd_cwnd <= tp->snd_ssthresh) {
        /* ABC 핵심: ACK된 바이트 수를 MSS로 나눠서 패킷 단위 증가
         * 기본 Reno는 ACK 개수만 세지만, ABC는 바이트 수를 센다
         */
        u32 delta = acked / tp->mss_cache;
        if (delta == 0)
            delta = 1;
        
        tp->snd_cwnd += delta;
        
        /* 상한 체크 */
        tp->snd_cwnd = min(tp->snd_cwnd, tp->snd_cwnd_clamp);
    } 
    /* Congestion Avoidance with ABC */
    else {
        /* ABC 핵심: 바이트 기준 선형 증가
         * 기본 Reno: cwnd += 1 MSS per RTT (ACK 개수 기준)
         * ABC: cwnd += bytes_acked / (cwnd * MSS) (바이트 기준)
         * 
         * 이렇게 하면 큰 MSS든 작은 MSS든 같은 바이트를 보내면
         * 같은 비율로 cwnd가 증가 → 공정성 확보
         */
        u32 w = tp->snd_cwnd;
        u32 target = w * tp->mss_cache;  // 1 RTT에 보낼 바이트 수
        
        /* acked 바이트가 target에 도달하면 cwnd를 1 증가 */
        if (acked >= target) {
            tp->snd_cwnd += acked / target;
        } else {
            /* 부분 증가: 크레딧 누적 방식 */
            tcp_cong_avoid_ai(tp, w, acked);
        }
        
        /* 상한 체크 */
        tp->snd_cwnd = min(tp->snd_cwnd, tp->snd_cwnd_clamp);
    }
}

/* undo_cwnd: 이게 없어서 에러 났던 것 */
u32 tcp_reno_abc_undo_cwnd(struct sock *sk)
{
    const struct tcp_sock *tp = tcp_sk(sk);
    return max(tp->snd_cwnd, tp->prior_cwnd);
}

static struct tcp_congestion_ops tcp_reno_abc = {
    .init           = tcp_reno_abc_init,
    .ssthresh       = tcp_reno_abc_ssthresh,
    .cong_avoid     = tcp_reno_abc_cong_avoid,
    .undo_cwnd      = tcp_reno_abc_undo_cwnd,  // ← 이게 핵심 수정
    .owner          = THIS_MODULE,
    .name           = "reno_abc",
};

static int __init tcp_reno_abc_register(void)
{
    int ret = tcp_register_congestion_control(&tcp_reno_abc);
    if (ret) {
        printk(KERN_ERR "TCP Reno ABC: registration failed (error %d)\n", ret);
        return ret;
    }
    printk(KERN_INFO "TCP Reno ABC: loaded successfully\n");
    return 0;
}

static void __exit tcp_reno_abc_unregister(void)
{
    tcp_unregister_congestion_control(&tcp_reno_abc);
    printk(KERN_INFO "TCP Reno ABC: unloaded\n");
}

module_init(tcp_reno_abc_register);
module_exit(tcp_reno_abc_unregister);

MODULE_AUTHOR("Student");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("TCP Reno with ABC (fixes MSS bias)");
