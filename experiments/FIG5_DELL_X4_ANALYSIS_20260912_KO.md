**DELL Figure 5 ×4 결과 분석 — 2026-09-12**

후속 상태: 아래 분석 이후 별도 요청으로 ThinkPad 커널에 종료 정리 패치를 반영하고 커밋했다. DELL 소스 변경분은 ThinkPad에 보존한 뒤 되돌렸다. 자세한 반영·검증 범위는 문서 마지막에 기록했다. 아래 성능 분석은 패치 적용 전 측정에 관한 것이다.

대상 결과는 `/home/leedaeeun/Documents/github/vldb26-iouring/results/figure5/dell-raw-x4-r10-20260911-232818/`이다. SSH로 원본 결과, 실행 당시 부팅의 커널 로그, 현재 DELL 커널 소스를 조회했다. 원본 측정 파일을 변경하지 않고 별도 복사본에서 집계했다. 분석 뒤 DELL 원본 163개 파일의 SHA256을 다시 계산해 처음 보관한 복사본과 모두 일치함을 확인했다.

**가장 유력한 결함 후보는 6.15.11의 NVMe IOPoll 완료 처리 변경과 관련 종료 정리 패치의 누락이다.** NVMe 완료를 `task_work`로 넘기는 변경은 들어 있지만, 그 변경에 대응하는 상류 종료 처리 패치 `b62e0efd8a85`의 코드가 없다. 해당 조건에서는 종료 중 완료 처리가 진전되지 않는 경로가 소스상 존재한다. 첫 polling 실험 이후 IOPoll만 반복해서 느려지는 결과와 부합한다. 다만 실험 당시 커널 작업자 스택과 CPU 사용률을 기록하지 않았고 이미 재부팅했으므로, 이 결함이 이번 성능 저하를 실제로 일으켰는지는 패치 전후 측정으로 확정해야 한다.

그와 별개로 논문 원본 CSV는 `6.15.0-rc7`, DELL은 `6.15.11-io_uring`을 기록한다. 두 버전의 NVMe IOPoll 완료 경로가 다르므로 CPU·SSD 사양뿐 아니라 커널 구현도 완전히 같은 비교가 아니다. 이 차이가 만드는 성능 손실의 크기는 이번 자료만으로 분리할 수 없다.

**실제 반복 횟수와 결과**

디렉토리 이름에는 `r10`이 있지만 `run.json`의 `args.repeats`는 **5**다. 실험 당시 sudo journal에도 `--repeats 5`가 남아 있다. 총 50개 항목이 모두 PASS했고 전체 상태는 COMPLETE다. 누락된 5회나 중간 실패로 인한 불완전 결과가 아니라, 처음부터 5회로 실행한 결과다. 실행 시간은 2026-09-11 23:28:24~23:46:47 KST이다.

논문 값은 `experiments/data/bench_buffer_mgr.csv`에서 같은 설정의 마지막 샘플을 선택했다. 이는 `experiments/plot_buffer_mgr.R`의 마지막 샘플 집계에 대응한다. DELL 값은 각 반복의 마지막 1초 TPS 5개의 중앙값이다. 논문 값에는 이 자료로 계산할 수 있는 반복 오차 범위가 없다.

| 항목 | 논문 원본 TPS | DELL 중앙값 TPS | DELL / 논문 차이 |
|---|---:|---:|---:|
| Posix | 16,465 | 20,342 | +23.6% |
| io_uring Sync | 16,549 | 20,312 | +22.7% |
| BatchEvict | 19,064 | 24,461 | +28.3% |
| libaio +Fibers | 173,001 | 229,054 | +32.4% |
| io_uring +Fibers | 183,472 | 230,683 | +25.7% |
| BatchSubmit | 216,608 | 267,259 | +23.4% |
| RegBufs | 237,778 | 283,481 | +19.2% |
| Passthru | 300,491 | 301,635 | +0.4% |
| IOPoll | 376,395 | 259,179 | −31.1% |
| SQPoll | 546,501 | 363,078 | −33.6% |

×4 전환 후 Passthru까지의 개선은 나타난다. 특히 Passthru는 논문 값과 가깝다. 문제는 IOPoll의 반복별 변화다. 논문 막대값에서 Passthru→IOPoll 개선은 +25.3%지만, DELL 중앙값은 −14.1%다.

| 반복 | Passthru TPS | IOPoll TPS | SQPoll TPS | IOPoll 안정 구간 평균 TPS |
|---|---:|---:|---:|---:|
| 1 | 297,071 | **343,930** | 363,078 | 344,788 |
| 2 | 302,013 | **257,607** | 361,826 | 258,142 |
| 3 | 300,152 | **256,717** | 363,081 | 257,314 |
| 4 | 301,635 | **259,957** | 361,402 | 260,156 |
| 5 | 301,651 | **259,179** | 367,126 | 259,370 |

IOPoll 2~5회의 중앙값은 첫 회보다 24.9% 낮다. 첫 회도 그대로 포함해서 분석했다. 로딩과 트랜잭션 처리가 섞인 첫 구간을 제외한 나머지 9개 구간의 평균에서도 하락이 유지된다. 따라서 마지막 샘플 선택이나 중앙값 계산만의 문제가 아니다. 로딩 경계의 쓰기 카운터에는 기존 계수기 초기화에 따른 unsigned underflow가 보이므로 그 구간의 I/O 통계는 분석에서 제외했다.

![논문과 DELL 비교 및 IOPoll 반복별 변화](../results/figure5/diagnosis-dell-raw-x4-r10-20260911-232818/comparison.png)

**설정 누락 여부**

50개의 `.command.json`, `.nvme.json`과 로그를 대조했다. 모든 항목 직전 SSD와 상위 PCIe 포트가 8.0 GT/s ×4였다. NVMe는 NUMA 1, 작업 CPU는 24, SQPoll CPU는 25다. 두 CPU는 서로 다른 물리 코어다. `poll_queues=1`, `io_poll=1`이며, 해당 부팅의 NVMe 초기화 로그에도 `31/0/1 default/read/poll queues`가 있다. 실험 장치는 `/dev/nvme0n1`과 대응하는 `/dev/ng0n1`이고 마운트·swap·holder는 없었다.

IOPoll 5회의 실행 인자는 모두 같았다. `concurrency=128`, `evict_batch=128`, `setup_mode=defer`, `nvme_cmds=true`, `iopoll=true`, 등록 링·파일·버퍼 활성화 상태다. 각 로그에서 fiber 0~127의 시작을 확인했다. 링 생성 플래그는 Passthru `80920`, IOPoll `80921`, SQPoll `72735`다. IOPoll의 추가 비트 1은 `IORING_SETUP_IOPOLL`이다. SQPoll은 IOPoll도 함께 사용하며 별도 CPU 25가 기록되어 있다. IOPoll 로그의 `sqpoll_cpu=0`은 SQPoll을 사용하지 않는 링의 기본 필드 값이며, 작업 CPU가 0이라는 뜻이 아니다.

현재 ThinkPad 소스의 해시는 해당 결과의 빌드 기록과 일치한다. 따라서 fibers가 빠졌거나 파일 모드로 잘못 실행한 것으로 설명할 수 없다. COMPLETE/PASS는 벤치마크 프로세스와 관측한 I/O 완료 검사가 성공했다는 뜻이다. 커널의 비동기 종료 작업까지 모두 정리됐다는 검사는 현재 runner에 없다.

**커널에서 확인한 구체적인 차이**

원본 CSV의 해당 열 항목은 모두 `kernel=6.15.0-rc7`이다. 논문 본문의 일반 실험 환경 표기인 6.15.0과 구분해야 한다. 사용자가 알려준 ThinkPad의 `/home/leedaeeun/Downloads/linux`도 Makefile에서 `6.15.0-rc7`임을 확인했다. 해당 작업 트리는 수정 사항이 없었고, 비교한 NVMe·io_uring 관련 6개 파일이 공식 v6.15-rc7 소스와 SHA256까지 일치했다. 이 로컬 소스와 DELL 소스의 직접 diff도 별도로 보관했다.

rc7과 6.15.11을 비교하면 `drivers/nvme/host/ioctl.c`의 `nvme_uring_cmd_end_io()`가 다음과 같이 바뀌었다.

| 커널 | polled NVMe uring_cmd 완료 처리 |
|---|---|
| v6.15-rc7 | polled 요청이면 `io_uring_cmd_iopoll_done()` 경로로 즉시 완료 처리 |
| v6.15.11 / 현재 DELL 소스 | `io_uring_cmd_do_in_task_lazy()`를 통해 `task_work`로 전달 |

상류 수정은 `9ce6c9875f3e995be5fd720b65835291f8a609b1`이며 DELL 이력에는 stable 백포트 `2df1baccc3f7409cc1e6f95b297c483c841ff21d`로 존재한다. 여러 링이 같은 polling queue를 사용할 때 한 링이 다른 링의 완료를 발견할 수 있으므로 올바른 링의 문맥으로 완료를 돌려보내려는 수정이다. [NVMe 유지보수자의 원문과 변경 코드](https://lists.infradead.org/pipermail/linux-nvme/2025-June/056917.html)

그 변경에 맞춰 작성된 상류 패치가 `b62e0efd8a8571460d05922862a451855ebdf3c6`이다. `io_iopoll_try_reap_events()`의 마지막에 아래 처리를 추가한다. [상류 커널 패치](https://github.com/torvalds/linux/commit/b62e0efd8a8571460d05922862a451855ebdf3c6)

```c
if (ctx->flags & IORING_SETUP_DEFER_TASKRUN)
    io_move_task_work_from_local(ctx);
```

DELL의 함수에는 이 코드가 없다. 커밋 제목으로 조회한 이력에도 대응 수정이 없었다. 이 상태는 DELL이 임의로 삭제한 차이가 아니다. 직접 내려받은 공식 v6.15.11의 해당 파일도 동일하다. `io_uring.c`, `sqpoll.c`, `rw.c`, `uring_cmd.c`, NVMe `ioctl.c`, `pci.c`, `blk-mq.c` 총 7개 파일은 DELL 소스와 공식 v6.15.11의 SHA256이 일치했다. 현재 부팅의 `/proc/config.gz`도 DELL 빌드 디렉토리의 `.config`와 일치한다. 이 검사는 관련 소스·구성 확인이며 바이너리 성능 검증은 아니다.

문제가 될 수 있는 경로는 다음과 같다.

1. IOPoll 실행은 `DEFER_TASKRUN`을 사용한다. 벤치마크 소스는 시간 만료 후 전체 미완료 I/O를 끝까지 처리하는 명시적 종료 절차 없이 fiber를 정리한다. `BufferManager` 소멸자도 비어 있고 명시적 `io_uring_queue_exit()` 호출은 없다. 프로세스 종료에 따른 커널 정리에 의존한다.
2. 커널의 `io_uring_try_cancel_requests()`는 `iopoll_list`가 비워질 때까지 `io_iopoll_try_reap_events()`를 호출한다. DELL 소스의 해당 반복문은 `io_uring/io_uring.c` 3109행에 있다.
3. 종료 중 새로 회수한 NVMe 완료가 링의 local `task_work`에 쌓일 수 있다. 그 작업이 실행되어야 완료 플래그가 갱신되고 `iopoll_list`에서 요청이 제거될 수 있다.
4. 위 상류 패치가 없으면 이 회수 단계에서 새로 생긴 local 작업을 옮기지 못하는 경로가 있다. 그 경우 커널 정리 작업이 polling을 반복하며 남을 수 있다. 하나뿐인 NVMe polling queue를 뒤따르는 실험도 사용하므로 간섭 가능성이 생긴다.

이것은 소스로 확인한 정리 경로의 결함 후보다. 실제 실험에서 작업자가 해당 경로에 남았다는 스택은 없다. 마지막 통계의 `io_out`은 미완료 I/O가 있었음을 보여주지만, 그것이 프로세스 종료 순간의 정확한 개수는 아니다. 정상적인 커널 종료 처리로 회수될 수도 있으므로 사용자 코드에 명시적 drain이 없다는 사실만으로 커널 누수를 단정하지 않는다.

다운로드한 원본 상류 패치는 [upstream-b62e0efd-iopoll-exit.patch](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/upstream-b62e0efd-iopoll-exit.patch)에 보관했다. **복사한 DELL 소스에 대한 `patch --dry-run`은 통과했다. 실제 커널 소스에는 적용하지 않았고, 빌드·설치·재부팅도 하지 않았다.**

**실행 이력이 원인 후보를 뒷받침하는 이유**

이번 부팅에서 처음 측정한 IOPoll은 약 344k TPS였고 이후에는 약 259k TPS였다. 매 반복에서 IOPoll 뒤에 SQPoll을 실행하므로 이 기록만으로 첫 IOPoll 자체의 종료 영향과 SQPoll의 영향을 분리할 수는 없다.

이전 ×4 부팅의 관련 결과도 확인했다. 18:56:41 기능 검사에서 IOPoll은 242,241 TPS였고, 전체 기능 검사를 다시 실행한 19:01:40 결과에서는 210,809 TPS였다. 같은 두 작은 검사에서 Passthru는 210,625→211,430, SQPoll은 322,428→322,425로 거의 같았다. 첫 작은 검사 뒤의 18:57:27 본 실험 IOPoll도 259,051 TPS였다. 두 작은 검사는 서로 같은 조건으로 비교했으며, 작은 검사와 본 실험의 절대 TPS는 직접 비교하지 않았다. 서로 다른 부팅에서도 초기 polling 실행 이후 IOPoll의 저하가 반복되는 정황이다.

| IOPoll 지표 | 첫 반복 | 반복 2~5 |
|---|---:|---:|
| 안정 구간 평균 TPS | 344,788 | 257,314~260,156 |
| `get_events` / 초 | 약 39,782 | 약 20,156~20,369 |
| 완료한 read+write / `get_events` | 12.20 | 17.91~17.99 |
| 로그의 `cycles/write` | 약 1,417 | 약 2,916~2,963 |

`get_events`는 사용자 reactor의 완료 수집 함수 호출 횟수다. 커널 내부 polling 횟수나 syscall의 정확한 횟수로 해석하면 안 된다. `cycles/write`는 eviction 탐색·준비·제출 구간의 RDTSC 경과량을 완료 쓰기 수로 나눈 값이며 SSD 쓰기 지연이나 PMU의 실제 CPU 실행 cycle 측정값이 아니다. 커널 대기, 선점, 경합도 섞일 수 있다. 따라서 이 자료는 IOPoll 경로의 실행 양상이 달라졌다는 근거이며, 특정 함수의 비용을 분리한 프로파일은 아니다.

**현재 자료로 확정할 수 없는 부분과 다음 검증**

DELL은 Xeon E5-2699 v4와 Samsung 970 EVO Plus, 논문의 환경은 EPYC 9654P와 Kioxia CM7-R이다. ×4는 PCIe 링크 폭을 회복한 것이며 CPU와 SSD의 성능을 논문 장비와 같게 만들지는 않는다. SQPoll이 논문의 546k TPS에 도달하지 않는 차이는 이 하드웨어 차이와 커널 처리 비용도 포함한다. 다만 같은 DELL에서 IOPoll 첫 회와 후속 회가 25%가량 갈리는 현상은 고정된 하드웨어 사양 차이만으로 설명되지 않는다.

실험 당시 CPU별 사용률·주파수·커널 스택·SSD 온도·SMART 추이는 저장되어 있지 않다. 과거 sysstat/atop 기록도 없었다. 해당 부팅의 커널 로그에는 측정 도중 NVMe timeout/reset 오류가 없었고, RCU grace period 지연 메시지는 측정 종료 뒤인 23:48:59부터 나타난다. 이 메시지에는 원인 작업자 스택이 없으므로 이번 저하의 직접 증거로 삼지 않았다.

현재 SSH로 조회한 부팅은 실험 부팅과 다르다. 현재 한가한 시스템 상태나 낮은 SSD 온도를 과거 실험의 상태로 소급하지 않는다. SSH의 비대화형 sudo가 허용되지 않아 root 권한의 새 런타임 추적도 수행하지 않았다. 이번 요청에서는 새 raw 쓰기 실험 자체를 실행하지 않았다.

우선 검증할 변경은 **6.15.11을 유지한 별도 빌드에 `b62e0efd` 종료 정리 수정만 반영하는 것**이다. NVMe의 링 문맥 정확성을 보장하는 `9ce6c987` 수정은 유지한다. 적용 전후 각각 초기 상태에서 IOPoll만 5회 연속 실행하고, 이어 전체 열 항목을 5회 실행해 첫 회 이후 저하와 커널 정리 작업 잔류가 사라지는지 확인한다. 동시에 `iou_exit`/`iou-sqp` 관련 작업자의 CPU 사용과 스택, SSD 온도를 기록해야 한다. 측정 조건은 128 fibers, 1천만 레코드, 1 GiB, CPU 24/25와 NUMA 1로 고정한다.

사용자 코드 측에서는 새 요청 중단→기존 I/O 완료→fiber 정리→링 해제 순서로 종료를 명확히 하는 보강도 검토할 수 있다. 커널 수정 효과와 분리해서 평가해야 한다. 10초를 늘리거나 첫 반복만 선택하거나 그래프 집계를 바꾸는 것으로 이 문제를 해결했다고 판단해서는 안 된다.

**보관한 근거와 재계산 방법**

- [비교 그림 PNG](../results/figure5/diagnosis-dell-raw-x4-r10-20260911-232818/comparison.png), [PDF](../results/figure5/diagnosis-dell-raw-x4-r10-20260911-232818/comparison.pdf), [항목별 비교 CSV](../results/figure5/diagnosis-dell-raw-x4-r10-20260911-232818/comparison.csv)
- [반복별 지표](../results/figure5/diagnosis-dell-raw-x4-r10-20260911-232818/per-repeat-metrics.csv), [경계 구간을 제외한 샘플](../results/figure5/diagnosis-dell-raw-x4-r10-20260911-232818/stable-samples.csv), [논문 원본에서 선택한 행](../results/figure5/diagnosis-dell-raw-x4-r10-20260911-232818/paper-last-samples.json)
- [실험 부팅의 커널 로그](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/experiment-boot-kernel-journal.log), [현재 조회와 실행 당시 sudo 명령](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/remote-readonly-evidence.json)
- [DELL과 공식 6.15.11 소스 해시 비교](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/kernel-source-comparison.json), [rc7→6.15.11 NVMe 변경](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/rc7-v61511-drivers_nvme_host_ioctl.c.diff), [상류 패치 적용 가능성 검사](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/upstream-b62e0efd-dry-run.txt)
- [사용자 rc7 소스 확인](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/user-rc7-source-comparison.json), [로컬 rc7와 DELL의 NVMe 직접 비교](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/user-rc7-vs-dell-drivers_nvme_host_ioctl.c.diff)
- [원본 측정 파일 해시](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/original-run-sha256.json), [DELL 원본 불변 확인](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/original-integrity-check.json), [재계산 스크립트](../build-fig5/validation/dell-raw-x4-r10-232818-analysis/analyze.py)

```bash
cd /home/leedaeeun/Documents/github/vldb26-iouring
python3 build-fig5/validation/dell-raw-x4-r10-232818-analysis/analyze.py
```

이 명령은 보관한 측정값을 읽어 별도 진단 폴더의 그림과 집계 파일만 다시 만든다. 벤치마크 실행이나 장치 접근은 하지 않는다.

**후속 코드 반영 및 소스 관리 — 2026-09-12**

ThinkPad의 `/home/leedaeeun/Documents/github/linux`에서 `io_uring/io_uring.c`의 `io_iopoll_try_reap_events()` 마지막에 상류 `b62e0efd`의 3줄을 반영했다. 커밋은 `fa80c299557da85e6a4b3bb212a7a7725361bd1a`이며, 브랜치는 `branch-v6.15.11`이다. NVMe 완료를 task_work로 넘기는 기존 수정은 유지했다. 상류 패치와 patch-id가 일치하며 checkpatch는 오류·경고 0개다. 기존 6.15.11 빌드 설정과 GCC 14로 변경한 `io_uring.o`만 별도 경로에 컴파일해 성공했다. 전체 커널 빌드·설치·재부팅·성능 재측정은 아직 수행하지 않았다.

사용자의 요청에 따라 소스 변경은 ThinkPad에서 관리한다. 정리 직전 양쪽 vldb26-iouring 저장소의 952개 항목을 대조해 파일 내용·모드·서브모듈 상태가 같음을 확인했다. 수정된 기존 파일 12개와 새 파일 14개는 ThinkPad에 보존하고 백업했다. 그 뒤 DELL에서는 기존 파일 12개를 HEAD로 restore하고, 새 파일 14개와 해당 Python 캐시를 삭제했다. DELL의 실험 결과와 빌드 산출물 60,304개 파일은 정리 전후 SHA256이 모두 일치했다. 산출물의 기존 ignore 규칙은 DELL의 `.git/info/exclude`로 옮겨 보존했다.

DELL의 vldb26-iouring HEAD는 `1b37a9013d5f528639e049a97f9752b258457590`, 커널 HEAD는 `e5de8b597212e19529bc0b86445e11de4a09bceb`이며 두 작업 트리 모두 수정 사항이 없다. DELL에는 위 커널 패치와 로컬 실험 runner 소스가 반영되어 있지 않다. 이후 DELL에서 수정 버전을 시험할 때는 ThinkPad 커밋을 전달한 뒤 해당 컴퓨터에서 빌드해야 한다. 위 재계산 명령도 현재는 runner 소스를 보존한 ThinkPad에서 실행한다.

ThinkPad의 Figure 5 테스트 32개가 통과했고, 보존한 기존 빌드의 소스·바이너리 해시도 일치했다. 이 검증은 실행 도구와 컴파일 상태를 확인한 것이며 IOPoll 성능 회복을 검증한 결과가 아니다.
