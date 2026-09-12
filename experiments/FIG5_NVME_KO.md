그림 5의 Passthru·IOPoll·SQPoll을 포함한 열 개 항목 실행

2026-09-11에 `raw-nvme` 실행 모드를 추가하고 ThinkPad와 DELL에 같은 코드를 반영했다. 기존 `file` 모드는 앞의 7개 항목을 유지한다. `raw-nvme` 모드에서는 세 항목을 실제 원본의 누적 설정으로 실행하고, 새 결과 CSV와 그래프에 포함한다.

**DELL 최신 진단:** `dell-raw-20260911-144325`는 열 항목 모두 PASS했지만 후반 처리량이 정체됐다. 이후 조회에서 SSD의 실제 연결이 PCIe 3.0 ×1, 최대 지원 폭은 ×4로 확인됐다. [원인 분석과 연결 수정 후 재실행 방법](FIG5_DELL_ANALYSIS_20260911_KO.md)을 먼저 확인한다. 새 runner는 PCIe 연결을 기록하고 `--min-pcie-width 4`를 지정하면 ×1 상태의 실행을 차단한다. 아래 마지막 절의 미실행 기록은 raw 장치 준비 이전 검증 이력이다.

**현재 DELL의 `/mnt/nvme0n1p1`에 파일을 만드는 방식으로는 마지막 세 항목을 실행할 수 없다.** NVMe passthrough는 파일시스템을 거치지 않고 namespace의 LBA에 직접 쓰기 때문이다. 이 실행기는 전체 namespace만 지원한다. `/dev/nvme0n1p1`처럼 파티션을 지정하는 방법이나, 파일의 물리 위치를 추정해 NVMe 명령을 보내는 방법은 지원하지 않는다.

`--confirm-device`를 지정한 실제 raw 실행은 namespace의 시작 부분부터 쓰며, **기존 파티션 테이블과 파일시스템 데이터가 손상되어 사용할 수 없게 될 수 있다.** 이 옵션은 장치의 현재 마운트·swap·사용 상태 검사를 우회하지 않는다. 코드 수정 요청에 따라 실행 기능은 준비했지만, 이번 작업에서는 장치 초기화·언마운트·부팅 설정 변경·재부팅·raw 쓰기를 수행하지 않았다.

사용자가 지정한 기존 결과 `results/figure5/dell-20260911-131224`를 확인했을 때 앞의 7개 항목은 모두 `PASS`였다. 마지막 3개 행의 `UNSUPPORTED`는 파일 모드에서 생성한 상태이며 실행 실패가 아니다. 해당 결과를 덮어쓰거나 CSV에 서로 다른 I/O 경로의 측정값을 합치지 않는다. 열 개 막대의 연속 비교를 위해서는 첫 7개도 같은 raw namespace에서 다시 측정한다.

| 모드 | 앞의 7개 항목 | Passthru / IOPoll / SQPoll |
|---|---|---|
| `--storage file` (기본값) | 새 일반 파일에 O_DIRECT I/O | `UNSUPPORTED` / 그래프 `N/A` |
| `--storage raw-nvme` | 전체 NVMe block namespace에 O_DIRECT I/O | 대응하는 generic character namespace에 NVMe uring_cmd |

마지막 세 항목은 다음 설정을 사용한다. 공통으로 concurrency 128, eviction batch 128, 제출 배치, 링·파일·버퍼 등록을 사용한다.

| 항목 | `nvme_cmds` | `iopoll` | `setup_mode` | 작업 / SQPoll CPU |
|---|---|---|---|---|
| `passthru` | true | false | defer | 작업 CPU만 지정 |
| `iopoll` | true | true | defer | 작업 CPU만 지정 |
| `sqpoll` | true | true | sqpoll | 서로 다른 물리 코어 지정 |

여기서 마지막 `sqpoll` 항목은 IOPoll도 계속 활성화한 구성이다. 일반 파일에서 SQPoll만 켠 결과는 원본의 마지막 막대와 조건이 다르다.

1. **실험용 namespace를 준비한다.**

   DELL에서 수정된 저장소는 `/home/leedaeeun/Documents/github/vldb26-iouring`이다. 추가 수정 후 재빌드할 때는 일반 사용자로 아래 명령을 사용한다. 이번 코드 반영 과정에서는 이미 양쪽에서 빌드를 완료했다.

   ```bash
   cd /home/leedaeeun/Documents/github/vldb26-iouring
   python3 experiments/build_fig5.py --jobs 8
   ```

   현재 확인한 DELL의 Samsung 970 EVO Plus namespace는 `/dev/nvme0n1`이고 generic character 경로는 `/dev/ng0n1`이다. 그 안의 `/dev/nvme0n1p1`은 `/mnt/nvme0n1p1`에 마운트되어 있어 현재 raw 실행 대상이 될 수 없다. 기존 SSD를 실험 전용으로 전환하려면 데이터 보존과 해당 namespace 전체의 사용 중단을 먼저 별도로 진행해야 한다. 새 전용 NVMe를 사용하는 방법도 있다.

   ThinkPad의 현재 NVMe에는 운영체제와 swap이 있으므로 raw 실행 대상으로 사용할 수 없다. ThinkPad에서도 같은 실행기를 사용할 수 있지만, 별도의 사용하지 않는 PCIe NVMe namespace를 준비해야 한다.

   실행 대상은 모델·일련번호·WWID·크기·namespace ID로 확인한다. 실행기는 마운트된 파티션, 활성 swap, device-mapper/RAID 등의 holder를 거부하고, 실행 중에는 block device를 `O_EXCL`로 열어 독점 사용을 유지한다. block/character 경로의 sysfs 대응 관계와 namespace ID도 확인한다. 직접 장치에 쓰므로 단순한 폴더 이름 확인만으로 진행하지 않는다.

2. **IOPoll용 NVMe polling queue를 준비한다.**

   확인 당시 두 컴퓨터 모두 `nvme.poll_queues=0`, namespace의 `queue/io_poll=0`이었다. Linux 커널 소스 수정 대신 기존 NVMe 드라이버의 polling queue 설정을 사용한다. NVMe 드라이버가 polling queue를 구성해야 한다는 요구는 [liburing의 io_uring_setup 문서](https://github.com/axboe/liburing/blob/master/man/io_uring_setup.2)에 설명되어 있다.

   DELL에는 `/etc/default/grub`, `/boot/grub/grub.cfg`, `grub-mkconfig`가 있음을 확인했다. GRUB의 커널 인자에 `nvme.poll_queues=1`을 추가해 적용하는 경우 아래 순서로 준비한다. 이 과정은 재부팅을 포함하므로 실행 중인 작업을 먼저 마친 상태에서 사용자가 진행한다.

   ```bash
   sudoedit /etc/default/grub
   ```

   `GRUB_CMDLINE_LINUX_DEFAULT`의 기존 인자들을 보존하고, 따옴표 안에 `nvme.poll_queues=1`을 추가한다. 이어서 설정을 생성하고 재부팅한다.

   ```bash
   sudo grub-mkconfig -o /boot/grub/grub.cfg
   sudo reboot
   ```

   재접속 후 실제 실행 중인 커널과 장치에서 적용 여부를 확인한다. 아래 두 번째 경로의 namespace 이름은 실험 장치에 맞춘다.

   ```bash
   cat /proc/cmdline
   cat /sys/module/nvme/parameters/poll_queues
   cat /sys/block/nvme0n1/queue/io_poll
   ```

   필요한 상태는 `poll_queues > 0`과 `io_poll=1`이다. 모듈 인자만 바꾸고 이미 생성된 I/O queue가 갱신되지 않은 상태는 통과시키지 않는다. 실제 polling 명령 성공은 이후 장치를 준비한 상태에서 기능 검사로 확인한다.

3. **실험 장치를 명시하고 읽기 전용 사전 점검을 실행한다.**

   아래의 `X`, `Y`를 실험 전용으로 준비한 장치 번호로 바꾼다. `/mnt/nvme0n1p1` 경로나 `/dev/nvme0n1p1` 파티션 경로를 지정하지 않는다.

   ```bash
   RAW_BLOCK=/dev/nvmeXnY
   RAW_CHAR=/dev/ngXnY

   sudo prlimit --memlock=2147483648:2147483648 \
     python3 experiments/run_fig5_local.py \
       --storage raw-nvme \
       --nvme-block "$RAW_BLOCK" --nvme-char "$RAW_CHAR" \
       --preflight
   ```

   이 `--preflight` 명령은 데이터 쓰기를 하지 않는다. 확인하는 것은 장치 식별과 사용 상태, CPU, polling queue, PCIe 연결, 빌드, 권한 및 memlock 한도다. root에서는 데이터 명령이 아닌 `NVME_IOCTL_ID`로 두 경로의 namespace ID도 대조한다. `errors: []`는 실행 조건 통과이며 논문과 같은 성능을 보장하지 않는다. `warnings`와 `nvme.pcie.links`도 확인한다. DELL 연결 수정 후 실험에서는 모든 명령에 `--min-pcie-width 4`를 추가한다. 실제 raw 실행에서는 별도로 `--confirm-device`가 필요하다.

   root로 실행하는 이유는 raw 장치 접근과 NVMe 명령 권한을 일관되게 준비하기 위해서다. `sudo prlimit ... python3 ...`는 해당 실행 프로세스에 2 GiB memlock 한도를 준다. Git은 선택한 이 저장소와 liburing 경로에 대해서만 명령별 `safe.directory`를 사용하며 시스템의 전역 Git 설정을 변경하지 않는다. root 실행으로 생성한 결과 디렉토리는 root 소유일 수 있으므로 아래 플롯 명령도 같은 방식으로 실행한다.

4. **실행할 명령을 확인한다.**

   ```bash
   sudo prlimit --memlock=2147483648:2147483648 \
     python3 experiments/run_fig5_local.py \
       --storage raw-nvme \
       --nvme-block "$RAW_BLOCK" --nvme-char "$RAW_CHAR" \
       --dry-run
   ```

   앞의 7개 명령에는 `--ssd "$RAW_BLOCK"`, 마지막 세 명령에는 `--ssd "$RAW_CHAR"`가 전달되는 것을 확인한다. `--dry-run`도 장치를 변경하지 않는다. 사전 점검이 실패하면 진단과 명령은 출력하지만 종료 코드 2를 반환하며 실제 실행하지 않는다.

   작업 CPU 기본값은 2, NUMA node는 0이다. SQPoll CPU를 생략하면 같은 NUMA node에서 작업 CPU와 다른 물리 코어를 선택한다. 현재 CPU 배치에서 DELL은 3, ThinkPad는 4가 선택됨을 확인했다. 명시하려면 `--sqpoll-cpu 3`처럼 지정한다. 작업 CPU의 SMT 형제는 거부한다.

5. **준비된 전용 장치에서 작은 raw 기능 검사를 실행한다.**

   **이 단계부터 실제로 namespace에 쓰기 때문에 기존 데이터와 파티션 테이블이 손상될 수 있다.** 파일 모드의 작은 검사와 달리 `--smoke`도 raw 장치를 보존하는 옵션이 아니다. 아래 명령은 사전 점검을 통과한, 직접 쓰기를 허용한 전용 장치에서만 사용한다.

   ```bash
   RAW_SMOKE="$PWD/results/figure5/raw-smoke-$(date +%Y%m%d-%H%M%S)"

   sudo prlimit --memlock=2147483648:2147483648 \
     python3 experiments/run_fig5_local.py \
       --storage raw-nvme \
       --nvme-block "$RAW_BLOCK" --nvme-char "$RAW_CHAR" \
       --confirm-device "$RAW_BLOCK" \
       --smoke --output-dir "$RAW_SMOKE"
   ```

   기본적으로 열 개 항목을 순서대로 실행한다. 작은 조건은 100,000개 레코드·4 MiB 버퍼 풀·로딩 후 3초다. 장치 쓰기 경로와 CQE 완료 상태를 확인하기 위한 검사이며 본 성능 수치가 아니다. 모든 항목의 `PASS`와 마지막 `COMPLETE`를 확인한다. NVMe 명령의 양수 오류 상태도 실패로 처리한다.

6. **열 개 항목을 같은 장치에서 본 측정한다.**

   ```bash
   RAW_RESULT="$PWD/results/figure5/raw-$(date +%Y%m%d-%H%M%S)"

   sudo prlimit --memlock=2147483648:2147483648 \
     python3 experiments/run_fig5_local.py \
       --storage raw-nvme \
       --nvme-block "$RAW_BLOCK" --nvme-char "$RAW_CHAR" \
       --confirm-device "$RAW_BLOCK" \
       --output-dir "$RAW_RESULT"
   ```

   기본 조건은 10,000,000개 레코드·1 GiB 버퍼 풀·항목별 로딩 후 10초·1회다. 원본 아티팩트의 `ycsb_read_ratio=0` 동작을 유지한다. raw 모드의 8 GiB 크기 검사는 장치의 최소 용량 검사이며 파일 할당이나 쓰기 범위 제한을 의미하지 않는다. 프로그램은 선택한 namespace의 처음부터 사용한다.

   세 항목만 별도로 기능 확인하려면 같은 명령에 `--cases passthru iopoll sqpoll`을 추가할 수 있다. 이 경우 첫 7개는 새 결과에서 `NOT_SELECTED`로 남는다. 기존 파일 결과에 붙여서 열 개 막대의 개선 효과를 계산하지 않는다.

7. **raw 결과로 그래프를 생성한다.**

   ```bash
   sudo python3 experiments/plot_fig5_local.py "$RAW_RESULT"
   ```

   성공한 세 항목도 실제 TPS 막대로 표시한다. 선택했으나 실패하거나 누락된 항목은 `INCOMPLETE`, 선택하지 않은 항목은 `NOT_SELECTED`로 남는다. raw 모드에서 마지막 세 항목을 무조건 `UNSUPPORTED`로 분류하지 않는다.

   `run.json`에는 `storage=raw-nvme`, 장치 모델·namespace 식별 정보·사용 상태·polling queue·선택한 CPU가 기록된다. 각 `.command.json`과 `.log`에는 실제 명령과 링 생성 플래그, SQPoll CPU, 완료 결과가 남는다. 원본 방식인 마지막 1초 TPS 샘플과 보조 평균의 차이는 [기존 실행 안내](FIG5_DELL_KO.md)에 설명되어 있다.

8. **이번 검증 범위를 구분한다.**

   ThinkPad와 DELL에서 두 백엔드의 Release 빌드, 자동 테스트 28개, 기존 파일 모드 7개 항목의 작은 기능 검사를 수행했다. 마운트·swap·holder 차단, block/character 장치 쌍 검증, 명시적 쓰기 확인과 독점 사용 해제, polling 준비 상태, SMT 회피, 누적 옵션, NVMe 양수 오류 상태, raw 결과 집계, 파일/raw 혼합 거부를 검사했다.

   실제 장치를 조회하는 사전 점검은 ThinkPad의 루트/EFI/데이터 마운트와 swap, DELL의 `/mnt/nvme0n1p1` 마운트, 양쪽의 polling queue 0 상태를 탐지해 실행을 거부했다. raw 파일 처리와 독점 사용의 성공 경로는 장치를 흉내 낸 단위 테스트이며, 이 결과를 실제 NVMe 쓰기·IOPoll·SQPoll 성능 성공으로 해석하지 않는다.

   **세 raw 항목의 실제 장치 I/O와 성능 측정은 아직 수행하지 않았다.** 전용 namespace와 polling 설정 준비 후 위 절차로 검증해야 한다. 코드와 검사 결과는 준비되어 있으며, 현재의 마운트된 NVMe를 그대로 사용할 수 있다는 의미는 아니다.
