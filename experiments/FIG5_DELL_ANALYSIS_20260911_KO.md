# DELL Figure 5 결과 진단 — 2026-09-11

대상은 `results/figure5/dell-raw-20260911-144325`이다. 열 항목 모두 PASS했고, Passthru·IOPoll·SQPoll 옵션도 실제 명령과 링 생성 로그에서 활성화됐다. **가장 먼저 해결할 문제는 SSD의 PCIe 연결 폭이다. 진단 시점에는 PCIe 3.0 ×1로 연결되어 있었다. SSD와 상위 포트의 최대 지원 폭은 ×4다.** 연결 수정 후 성능 검증은 아직 하지 않았다.

**어댑터 확인에 따른 정정:** 사용자가 현재 어댑터가 **넥시 NX1247(NX-M2-PX4C)**이라고 확인했다. 이 모델은 NVMe용 PCIe ×4 확장 카드다. 현재 연결 폭 `1`만으로 어댑터를 ×1 전용이라고 판단하거나 같은 모델의 추가 구매를 권하는 것은 적절하지 않다. 새 제품 구매는 보류하고 기존 카드의 장착 상태와 슬롯을 먼저 점검한다. [제조사 카탈로그](https://river1320.godohosting.com/NEXI_HP/DRIVER/NEXI_CATALOGO_2019-2024.pdf)

추가 읽기 전용 조회에서도 NVMe와 상위 포트는 각각 최대 ×4 / 실제 ×1이었다. 두 장치는 조회 시 D0, runtime active 상태였고, 노출된 AER 오류 누계는 0이었다. 오류 누계 0은 접촉 불량이나 링크 초기화 문제를 배제하는 근거가 아니다. 소프트웨어에 표시된 `Physical Slot: 43`을 메인보드 실크 인쇄의 SLOT 번호로 곧바로 해석할 수 없으므로 실제 장착 위치와 라이저·연장 케이블 유무는 사용자 확인이 필요하다. ×1 제한의 구체적인 원인은 아직 확정되지 않았다.

## 결과와 근거

원본 논문 CSV `experiments/data/bench_buffer_mgr.csv`에서 같은 YCSB 설정의 마지막 샘플을 선택했다. DELL도 기존 runner의 마지막 1초 TPS를 사용한다. 모두 1 GiB 버퍼 풀, 1천만 레코드, 4 KiB 페이지, 한 작업 스레드, 비동기 항목은 128 fibers 조건이다.

| 항목 | 논문 원본 TPS | DELL TPS |
|---|---:|---:|
| Posix | 16,465 | 18,867 |
| io_uring Sync | 16,549 | 18,964 |
| BatchEvict | 19,064 | 23,097 |
| libaio + Fibers | 173,001 | 201,783 |
| io_uring + Fibers | 183,472 | 202,360 |
| BatchSubmit | 216,608 | 232,642 |
| RegBufs | 237,778 | 235,650 |
| Passthru | 300,491 | 237,006 |
| IOPoll | 376,395 | 234,794 |
| SQPoll | 546,501 | 236,488 |

DELL은 앞부분의 개선을 재현했고, BatchSubmit 이후 처리량이 정체됐다. 마지막 샘플 대신 경계 구간을 제외한 9개 샘플 평균으로 보아도 같은 현상이다. RegBufs/Passthru/IOPoll/SQPoll 평균은 각각 약 239k/240k/239k/239k TPS다. 집계 방법만 바꿔서 해결되는 문제가 아니다.

DELL에서 읽기 전용으로 조회한 값:

```text
NVMe: Samsung SSD 970 EVO Plus 1TB
PCI endpoint 0000:07:00.0: current 8.0 GT/s, x1; maximum 8.0 GT/s, x4
Upstream port 0000:00:03.3: current 8.0 GT/s, x1; maximum 8.0 GT/s, x4
PCI NUMA node: 0
kernel: 6.15.11-io_uring
nvme.poll_queues: 1
queue/io_poll: 1
worker CPU: 2; SQPoll CPU: 3 (별도 물리 코어, NUMA 0)
```

PCIe 3.0 ×1의 한 방향 대역폭 상한은 `8e9 × 128/130 ÷ 8 ≈ 985 MB/s`이며, 프로토콜 오버헤드를 빼기 전 값이다. DELL 후반부에서는 읽기와 쓰기가 각각 약 670~680 MB/s로 정체된다. 논문 SQPoll 로그의 읽기는 `386002 × 4096 ≈ 1,581 MB/s`로, ×1 링크에서는 이 읽기량 자체가 불가능하다. 읽기·쓰기는 서로 반대 방향을 사용하므로 두 값을 더해서 한 방향 상한과 비교하면 안 된다.

이 수치는 PCIe 또는 SSD 쪽 한계가 후반의 CPU 비용 절감 효과를 가리고 있다는 설명과 부합한다. 다만 **기존 run.json에는 PCIe 정보가 없고, ×1은 실험 이후 확인한 값**이다. 링크 폭을 바꾼 전후 실험이 없으므로 처리량 정체의 유일한 원인이라고 확정하지 않는다.

논문은 AMD EPYC 9654P와 Kioxia CM7-R PCIe 5.0 SSD를 사용한다. DELL은 Xeon E5-2699 v4와 소비자용 970 EVO Plus다. ×4로 수정해도 논문과 같은 수치나 모든 항목의 단조 증가를 보장할 수 없다. 단일 SSD 실험끼리 비교한 것이며 논문의 SSD 8개를 합산한 값과 비교한 것은 아니다.

추가 관찰: 진단 시 `kworker/u353:7+iou_exit`(당시 PID 1541)가 한 CPU를 거의 계속 사용했다. 프로세스 시작 시각은 실험보다 앞선 부팅 초기였다. 이것을 이번 raw 실험의 오류라고 단정할 근거는 없다. 재부팅 후에도 같은 현상이 지속되면 해당 PID의 커널 스택을 root로 수집해 별도 분석해야 한다. SSH 세션에서는 비대화형 sudo가 허용되지 않아 스택은 수집하지 못했다. 드라이버 변경, 커널 재빌드, APST/IOMMU 변경으로 효과를 확인한 상태도 아니다.

마지막 재점검에서는 같은 SSD의 `/dev/nvme0n1p1`이 `/mnt/nvme0n1p1`에 ext4로 마운트되어 있었다. 진단 중 상태가 바뀌었으므로 현재 상태에서 raw 실험은 실행할 수 없다. 이 마운트 상태를 과거 14:43 실험에 소급해서 적용하지 않는다. 도구는 현재 마운트도 탐지해 실행을 차단했다.

## 코드 수정

- `fig5_nvme.py`: sysfs에서 SSD와 상위 PCIe 링크의 실제/최대 폭·속도·NUMA를 수집한다. SSD가 최대 폭보다 좁게 연결되면 경고한다.
- `run_fig5_local.py`: `--min-pcie-width 4`를 추가했다. 요청 폭보다 좁거나 확인할 수 없으면 사전 점검과 raw 장치 독점 사용 단계, 각 항목 실행 직전에서 중단한다. `run.json`과 각 `rXX-CASE.nvme.json`에 상태를 기록한다.
- `plot_fig5_local.py`: 새 결과에 기록된 PCIe 정보를 그래프에 표시한다. 기존 결과에 실험 이후 조회한 정보를 소급해서 넣지 않는다.

기본 실행은 좁은 링크를 경고하고 허용한다. ×1 자체를 측정하려는 실험도 있기 때문이다. **아래 재실험에서는 반드시 `--min-pcie-width 4`를 사용한다.** 이 옵션은 lane 수를 설정하는 명령이 아니라 실험 조건 검사다. SSD 속도나 논문 성능을 보장하는 검사도 아니다. 벤치마크 C++ 코드와 작업량은 그대로이므로 이 Python 변경 때문에 다시 빌드할 필요는 없다.

## DELL에서 해결하고 재실행하는 순서

1. 현재 사용하는 NX1247을 유지한다. DELL을 종료하고 전원을 분리한 뒤 SSD와 어댑터의 M.2 연결, 어댑터와 PCIe 슬롯의 장착 상태를 확인하고 다시 고정한다. 동일 슬롯에서 재부팅해 연결 폭을 확인한다. 여전히 ×1이면 다음 단계의 다른 사용 가능한 PCIe 3.0 슬롯에서 비교한다. 라이저·연장 케이블을 사용 중이라면 그 규격도 확인하고, 가능한 경우 메인보드 슬롯에 직접 장착해 비교한다. 각 변경 후 연결 폭을 확인해야 어느 조건에서 달라졌는지 판단할 수 있다. 현재 실제 슬롯 위치와 중간 연결 장치 유무는 아직 확인되지 않았다.
2. T7910 공식 사양에서 CPU1 영역의 SLOT1은 PCIe 3.0 ×4 전기 연결, SLOT2/4는 PCIe 3.0 ×16이고 SLOT3은 PCIe 2.0이다. 보드 표기와 어댑터를 대조해 선택한다. CPU2 영역으로 옮기면 NVMe NUMA node와 작업/SQPoll CPU도 다시 선택해야 한다. 아래 CPU 2/3, NUMA 0 명령은 SSD가 계속 NUMA 0일 때 사용한다.
3. 다시 `6.15.11-io_uring`으로 부팅한다. 이미 적용한 `nvme.poll_queues=1`은 유지한다. 포맷이나 `wipefs`, `blkdiscard`를 다시 할 필요는 없다. 슬롯 이동 후 장치 번호가 바뀔 수 있으므로 실험 전용 SSD 모델·serial·마운트 여부를 먼저 확인한다.

```bash
cd /home/leedaeeun/Documents/github/vldb26-iouring
uname -r
lsblk -o NAME,MODEL,SERIAL,SIZE,FSTYPE,MOUNTPOINTS

# 준비한 전용 970 EVO Plus가 여전히 이 장치 번호일 때만 사용한다.
# 확인한 serial: S4EWNM0W327482P
RAW_BLOCK=/dev/nvme0n1
RAW_CHAR=/dev/ng0n1

# 데이터 쓰기 없는 점검. errors: []와 PCIe x4, NUMA node를 확인한다.
sudo prlimit --memlock=2147483648:2147483648 \
  python3 experiments/run_fig5_local.py \
  --storage raw-nvme --nvme-block "$RAW_BLOCK" --nvme-char "$RAW_CHAR" \
  --cpu 2 --numa-node 0 --sqpoll-cpu 3 --min-pcie-width 4 --preflight
```

현재 ×1 상태에서는 위 검사가 실패하는 것이 의도한 동작이다. 마운트 오류도 나오면, 그 파일시스템에 보존할 데이터나 실행 중인 작업이 없는 전용 실험 장치인지 먼저 확인하고 `sudo umount /mnt/nvme0n1p1`로 해제한 뒤 사전 점검을 다시 실행한다. ×4와 장치/CPU 조건이 확인된 다음 아래 본 실험을 실행한다. 이 단계는 선택한 **전체 namespace에 쓰며 파티션 테이블과 데이터를 보존하지 않는다.** 기존에 실험 전용으로 준비한 SSD만 지정한다.

```bash
FIG5_RESULT="$PWD/results/figure5/dell-raw-x4-$(date +%Y%m%d-%H%M%S)"
sudo prlimit --memlock=2147483648:2147483648 \
  python3 experiments/run_fig5_local.py \
  --storage raw-nvme --nvme-block "$RAW_BLOCK" --nvme-char "$RAW_CHAR" \
  --confirm-device "$RAW_BLOCK" \
  --cpu 2 --numa-node 0 --sqpoll-cpu 3 --min-pcie-width 4 \
  --output-dir "$FIG5_RESULT"

# 위 실행이 COMPLETE로 끝난 뒤에만 그래프를 만든다.
sudo python3 experiments/plot_fig5_local.py "$FIG5_RESULT"
```

먼저 기존과 같은 10초·1회·논문 순서로 비교한다. 이후 반복 변동을 확인하려면 새로운 결과 경로로 `--repeats 3 --order shuffle --seed 20260911`을 추가한다. 결과가 계속 평평하면 SSD의 혼합 랜덤 I/O 한계, CPU 실행 비용, 위 커널 작업자를 다음 원인으로 분리해서 측정해야 한다. 작업량을 축소하거나 최적화별로 다른 조건을 적용해 논문처럼 보이게 만들지 않는다.

## 근거 파일과 검증 범위

- [비교 그래프](../results/figure5/diagnosis-dell-raw-20260911-144325/comparison.png), [계산값 CSV](../results/figure5/diagnosis-dell-raw-20260911-144325/comparison.csv)
- [실험 이후 환경 조회](../results/figure5/diagnosis-dell-raw-20260911-144325/live-environment.json), [기존 결과 SHA256](../results/figure5/diagnosis-dell-raw-20260911-144325/original-run-sha256.json)
- ThinkPad와 DELL에 동일한 코드를 반영했고 각 호스트에서 자동 테스트 32개가 통과했다. PCIe ×1 거부, ×4 허용, 상위 링크 제한, 폭 미확인 거부, 실제 장치 open 전 차단을 포함한다. DELL 실제 장치의 ×1과 마운트 상태도 읽기 전용 조회로 탐지했다. [마지막 사전 점검](../results/figure5/diagnosis-dell-raw-20260911-144325/final-preflight.json)에서 root/memlock 오류는 에이전트의 일반 SSH 세션 조건이며, 위 sudo prlimit 실행 조건과 구분한다.
- 기존 결과 33개 파일의 SHA256이 모두 일치함을 재확인했다. 이번 진단에서 새 성능 측정은 수행하지 않았다. 실제 성능 회복 여부는 위 하드웨어 수정 후 실험으로 판단한다.

하드웨어 근거: [Samsung 공식 970 EVO Plus 데이터시트](https://download.semiconductor.samsung.com/resources/data-sheet/Samsung_NVMe_SSD_970_EVO_Plus_Data_Sheet_Rev.3.0_10129514071343.pdf), [Dell 공식 T7910 슬롯 사양](https://www.dell.com/support/manuals/en-gy/precision-t7910-workstation/precision_t7910_om_pub/technical-specifications?guid=guid-26ef0634-418a-464a-a66f-bbcdf23ce58f&lang=en-us). 데이터시트의 최대 순차/랜덤 성능은 이 DBMS 혼합 I/O 실험의 보장값이 아니다.
