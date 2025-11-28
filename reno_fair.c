#include <linux/module.h>
#include <linux/kernel.h>
#include <net/tcp.h>

/* * 기준 RTT 설정 (단위: 마이크로초)
 * 실험에서 "Fast Group"의 RTT가 약 10ms(10000us)였으므로 이를 기준으로 잡습니다.
 * 이 값보다 RTT가 긴 연결들은 가중치를 받아 더 빨리 성장합니다.
 */
#define BASE_RTT_US 10000 

void tcp_fair_init(struct sock *sk)
{
    /* 초기 변수 설정: 기존 Reno와 동일하게 시작 */
    tcp_sk(sk)->snd_ssthresh = TCP_INFINITE_SSTHRESH;
    tcp_sk(sk)->snd_cwnd = 1;
}

u32 tcp_fair_ssthresh(struct sock *sk)
{
    /* 패킷 손실 시 감소 로직: 기존 Reno와 동일 (반토막) */
    const struct tcp_sock *tp = tcp_sk(sk);
    return max(tp->snd_cwnd >> 1U, 2U);
}

/* * [핵심 수정 부분] 
 * 혼잡 회피 단계에서 윈도우 증가 로직을 RTT 기반으로 변경 
 */
void tcp_fair_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
    struct tcp_sock *tp = tcp_sk(sk);
    
    // 1. cwnd가 제한된 상태인지 확인 (보낼 데이터가 없으면 증가 안 함)
    if (!tcp_is_cwnd_limited(sk))
        return;

    // 2. Slow Start 구간 (ssthresh보다 작을 때)
    if (tp->snd_cwnd <= tp->snd_ssthresh) {
        // Slow Start는 기존 Reno와 동일하게 지수적 증가 (RTT 보정 안 함)
        acked = tcp_slow_start(tp, acked);
        if (!acked)
            return;
    } 
    // 3. Congestion Avoidance 구간 (ssthresh보다 클 때)
    else {
        /* * 여기서 RTT 보정을 수행합니다.
         * tp->srtt_us: Smoothed RTT (단위가 us * 8 로 저장되어 있음)
         */
        u32 current_rtt_us = tp->srtt_us >> 3; // 실제 RTT(us) 추출
        u32 rtt_ratio = 1;

        // 현재 RTT가 기준(10ms)보다 크면 가중치(ratio)를 계산
        if (current_rtt_us > BASE_RTT_US) {
            // 예: RTT가 200ms면 ratio는 20이 됨
            rtt_ratio = current_rtt_us / BASE_RTT_US;
        }

        /* * tcp_cong_avoid_ai 함수는 (acked)만큼 카운터를 올립니다.
         * 여기서 acked에 rtt_ratio를 곱해서 넘겨줍니다.
         * 즉, ACK 1개를 받았지만, 마치 ACK 20개를 받은 것처럼 속여서 윈도우를 빨리 키웁니다.
         */
        tcp_cong_avoid_ai(tp, tp->snd_cwnd, acked * rtt_ratio);
    }

    // cwnd가 시스템 MAX치를 넘지 않도록 안전장치
    tp->snd_cwnd = min(tp->snd_cwnd, tp->snd_cwnd_clamp);
}

u32 tcp_fair_undo_cwnd(struct sock *sk)
{
    return tcp_sk(sk)->snd_cwnd;
}

/* 모듈 구조체 정의 */
static struct tcp_congestion_ops tcp_reno_fair = {
    .init           = tcp_fair_init,
    .ssthresh       = tcp_fair_ssthresh,
    .cong_avoid     = tcp_fair_cong_avoid,
    .undo_cwnd      = tcp_fair_undo_cwnd,

    .owner          = THIS_MODULE,
    .name           = "reno_fair", // sysctl에 등록될 이름
};

static int __init tcp_fair_module_init(void)
{
    // 구조체 크기 검증 (안전장치)
    BUILD_BUG_ON(sizeof(struct tcp_congestion_ops) != sizeof(struct tcp_congestion_ops));
    
    // 커널에 알고리즘 등록
    if (tcp_register_congestion_control(&tcp_reno_fair))
        return -ENOBUFS;
        
    printk(KERN_INFO "TCP Reno Fair Module Loaded\n");
    return 0;
}

static void __exit tcp_fair_module_exit(void)
{
    // 커널에서 알고리즘 제거
    tcp_unregister_congestion_control(&tcp_reno_fair);
    printk(KERN_INFO "TCP Reno Fair Module Unloaded\n");
}

module_init(tcp_fair_module_init);
module_exit(tcp_fair_module_exit);

MODULE_AUTHOR("Student");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("RTT-Fair TCP Reno");