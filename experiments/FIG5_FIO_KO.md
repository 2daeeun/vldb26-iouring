# Figure 5를 위한 fio 비교 실험

## 목적과 해석 범위

`run_fig5.py --method dbms`는 기존 `buffer_mgr` 실험을 실행한다.
`--method fio`는 설치된 Flexible I/O Tester를 실행하여 I/O 경로별 IOPS를 비교한다.
기존 `run_fig5_local.py`, `plot_fig5_local.py` 명령도 그대로 사용할 수 있다.

fio 자체의 소스 수정은 필요 없다. DELL에서 확인한 설치본은 `/usr/bin/fio`의
fio 3.42다. 실행기는 바이너리 경로·버전·SHA-256을 기록한다. 다른 fio를 쓰려면
`--fio /절대경로/fio`를 지정한다. 두 컴퓨터의 성능을 비교할 때는 버전과 옵션을 맞춘다.

**이 실험은 논문의 DBMS 처리량을 그대로 재현하지 않는다.** fio에는 B-tree 연산,
버퍼 풀의 적중·퇴거, fibers 스케줄링이 없다. 따라서 `BatchEvict`에 해당하는 막대를
만들지 않고 9개 I/O 구성을 측정한다. `iodepth=128`은 동시에 진행하는 I/O 수의 상한이며
128 fibers와 같지 않다. 실제 달성한 큐 깊이도 JSON에서 확인해야 한다.

주 실험은 `randrw`, 읽기 50%·쓰기 50%다. 논문 원본 결과의 마지막 표본에서 Posix의
초당 읽기/쓰기는 11,709/11,710, RegBufs는 161,475/160,655,
IOPoll은 265,696/263,994로 물리적 I/O가 약 1:1이었다.
논리적 YCSB 읽기 비율을 fio의 `rwmixread`로 그대로 옮기지 않았다.
저장소에서 추출한 근거는
`results/figure5/diagnosis-dell-raw-x4-r10-20260911-232818/paper-last-samples.json`이며
이 결과 경로는 Git 추적 대상이 아니다. I/O의 주소 분포·시간적 특성까지 같다는 뜻은 아니다.

추가로 `--workloads randrw randread`를 지정하면 읽기 전용 대조 실험도 실행한다.
각 workload를 별도 그래프로 표시하며, 결과를 보고 유리한 workload만 고르지 않는다.
**최적화 단계를 추가할 때 항상 빨라진다고 가정하지 않는다.** 작은 I/O의 CPU 비용,
SSD 처리 한계, polling의 CPU 소비, 쓰기 지연 등을 측정으로 구분한다.

## 비교 구성

모든 구성은 작업 스레드 하나, 4 KiB, 동일한 주소 범위를 사용하며 페이지 캐시를 우회한다.
일반 파일·블록 장치 경로는 `direct=1`을 사용한다. NVMe 명령을 보내는 마지막 세 구성은
`/dev/ng0n1` 문자 장치에 `direct=0`을 지정한다. Linux 6.15의 이 문자 장치는
O_DIRECT 열기를 EINVAL로 거부한다. `io_uring_cmd`는 NVMe 명령 자체로 데이터를 전송하므로
여기서 `direct=0`은 페이지 캐시를 사용하는 파일 I/O로 바꾸는 옵션이 아니다.
이 차이는 DELL 실측의 `open(/dev/ng0n1)` 오류로 확인했고, 회귀 테스트로 보호한다.
관련 예시는 [fio NVMe 명령 예제](../fio/examples/uring-cmd-ng.fio)를 참고한다.
비동기 구성의 QD는 128이고 완료 대기는 최소 1개, 한 번에 최대 QD개를 회수한다.
`iodepth_low=QD`를 유지하며 제출 배치만 바꾼다. QD 1 구성은 동기 경로의 기준이다.

| ID | 엔진 | QD | 제출 배치 | 누적 변경 |
|---|---|---:|---:|---|
| `posix` | psync | 1 | 1 | 동기 pread/pwrite |
| `uring_sync` | io_uring | 1 | 1 | io_uring에서 하나씩 완료 대기 |
| `libaio_async` | libaio | 128 | 1 | libaio 비동기 비교군 |
| `uring_async` | io_uring | 128 | 1 | io_uring 비동기 기준 |
| `batch_submit` | io_uring | 128 | 32 | SQE 제출 묶음 |
| `regbufs` | io_uring | 128 | 32 | fixedbufs=1, registerfiles=1 |
| `passthru` | io_uring_cmd | 128 | 32 | cmd_type=nvme, `/dev/ng0n1` 사용 |
| `iopoll` | io_uring_cmd | 128 | 32 | hipri=1 |
| `sqpoll` | io_uring_cmd | 128 | 32 | hipri=1 유지, sqthread_poll=1, SQPoll CPU 지정 |

비교군인 libaio를 제외하면 단계별 변경을 누적한다. io_uring 구성은
`nonvectored=1`, `force_async=0`을 명시한다. QD와 제출 배치는 각각
`--queue-depth`, `--batch-size`로 바꿀 수 있지만, 같은 비교 실험 내에서는 고정한다.
fio의 제출 배치 32는 논문의 eviction batch 128과 별개다.

fio 엔진이 설정하는 ring 플래그도 DBMS와 완전히 같지는 않다.
fio 3.42 소스는 COOP_TASKRUN, SINGLE_ISSUER, DEFER_TASKRUN을 요청하고
EINVAL 시 일부 플래그를 제거해 재시도한다. SQPoll과의 조합에서는 이 경로의 영향을 받는다.
이 실행기는 적용된 모든 ring 플래그를 커널에서 추적한 결과라고 주장하지 않는다.
옵션 의미는 [fio 공식 문서](https://fio.readthedocs.io/en/latest/fio_doc.html),
실제 설정 경로는 [fio 3.42 엔진 소스](https://github.com/axboe/fio/blob/fio-3.42/engines/io_uring.c)를 참고한다.

## 기본 측정 조건

| 항목 | 기본값과 의미 |
|---|---|
| 시험 범위 | offset 0부터 8 GiB; `--size-bytes`로 조절 |
| 초기화 | 새 실행마다 시험 범위를 1 MiB 순차 쓰기로 1회 채우고 fsync; 측정 통계에서 제외 |
| 측정 | 구성당 5초 ramp 후 30초; 각각 `--ramp-seconds`, `--duration-ms` |
| 반복 | 기본 10회; 검증 시 `--repeats 1` |
| 순서 | 기본 rotate: seed로 첫 순서를 정하고 반복마다 시작 위치를 한 칸 이동 |
| 난수 | 기본 seed 42; 같은 반복의 모든 구성은 동일한 주소 난수 seed |
| 데이터 버퍼 | refill_buffers=1; 매번 채우는 비용도 측정에 포함 |
| DELL 배치 | CPU 24, NUMA 1; SQPoll은 별도 물리 코어 CPU 25 |
| 로그 | 원본 JSON, 실행 명령, job 파일, 1초 IOPS 로그, CPU 관측치 |

rotate는 9회 동안 각 구성이 모든 순서 위치에 한 번씩 오게 한다. 10회째는 첫 위치가
반복되므로 완벽히 균등하지는 않다. `--order paper`는 항상 표 순서로 실행하며
`--order shuffle`은 반복마다 섞는다. 실제 순서는 `run.json`의 `trials`에 보존한다.

초기화는 SSD 전체를 포맷·discard하거나 장기 steady state를 보장하는 과정이 아니다.
8 GiB 범위와 소비자용 SSD의 캐시·GC·온도에 따른 영향을 남긴다. 서로 다른 반복 수,
범위, fio 버전, 큐 깊이를 하나의 결과처럼 합치지 않는다. 실험 전후 상태가 달라져도
논문과 닮은 결과만 선택하지 않고 원본을 보존한다.

## DELL에서 실행

코드를 ThinkPad에서 관리한 뒤 DELL의 실행용 복사본에 전달하여 실행한다.
이 문서의 명령은 DELL의 저장소에 수정본이 있는 경우의 경로다.
임시 복사본을 사용한다면 첫 `cd`만 그 경로로 바꾼다.
설치된 fio를 사용하므로 별도 fio 컴파일이나 fio 전용 서브모듈은 필요 없다.

실행용 저장소 루트의 `password.conf`에 해당 컴퓨터의 sudo 비밀번호를 한 줄로 넣고
`chmod 600 password.conf`를 실행한다. 파일이 없으면 `password.conf.example`을
복사해 작성한다. `PASSWORD=비밀번호` 형식도 지원하며, 따옴표나 shell escaping을
추가하지 않는다. 첫 번째 비어 있지 않은 비주석 줄을 사용하고 파일을 shell 코드로 실행하지 않는다.
`sudo_exec.sh`는 `sudo -A`를 사용하므로 SSH에서도 터미널 비밀번호 입력이 필요 없다.
비밀번호는 명령 인자나 실험 결과에 저장하지 않으며 파일은 Git에서 제외된다.
파일은 일반 파일·호출 사용자 소유·권한 600이어야 한다. 다른 저장소의 비밀번호를
자동으로 읽거나 복사하지 않는다. 인증만 확인하려면 `./sudo_exec.sh --check`를 사용한다.

필요한 프로그램은 `python3`, `fio`, `numactl`, `findmnt`, `git`, `matplotlib`이다.
Arch/EndeavourOS에서 누락된 패키지는 다음과 같이 설치할 수 있다.

```bash
sudo pacman -S --needed fio numactl util-linux git python python-matplotlib
```

1. 장치와 공통 옵션을 확인한다.

```bash
cd /home/leedaeeun/Documents/github/vldb26-iouring
uname -r
hostname
lsblk -d -o NAME,MODEL,SERIAL /dev/nvme0n1
FIG5_ARGS=(
  --method fio --fio /usr/bin/fio --storage raw-nvme
  --nvme-block /dev/nvme0n1 --nvme-char /dev/ng0n1
  --cpu 24 --numa-node 1 --sqpoll-cpu 25 --min-pcie-width 4
)
```

확인한 DELL은 `arch`, Samsung 970 EVO Plus 1TB,
일련번호 `S4EWNM0W327482P`다. `/dev/nvme0n1p1` 파티션 경로나
이전에 마운트했던 `/mnt/nvme0n1p1` 디렉터리를 raw 장치로 지정하지 않는다.
**raw 실행은 장치 시작 부분부터 쓰므로 파티션 정보와 기존 데이터가 손상될 수 있다.**

2. 사전 점검 결과가 `errors: []`인지 확인한다.

```bash
./sudo_exec.sh experiments/run_fig5.py "${FIG5_ARGS[@]}" --preflight
```

마운트, swap, block holder, 장치 쌍, NUMA, PCIe 폭, polling queue, CPU,
memlock, fio 엔진을 점검한다. 실행 직전에는 동일한 장치인지 재확인하고
실험 종료까지 block 장치를 독점 claim하여 새 마운트를 막는다.
root와 높은 memlock이 필요한 것은 장치 접근 및 등록 버퍼 사용 때문이다.
`sudo_exec.sh`가 실행기에 memlock 2 GiB를 설정한다. 기존의 직접 `sudo prlimit` 실행도 가능하다.
사전 점검이 fio 옵션의 런타임 지원이나 부팅 커널의 소스 패치까지 증명하지는 않는다.

3. 9개 구성을 1회씩 실행한다.

```bash
FIG5_RESULT="$PWD/results/figure5/dell-fio-r1-$(date +%Y%m%d-%H%M%S)"
./sudo_exec.sh experiments/run_fig5.py "${FIG5_ARGS[@]}" \
  --confirm-device /dev/nvme0n1 --repeats 1 --output-dir "$FIG5_RESULT"
```

초기화 PASS 후 9개 구성 각각 PASS, 마지막 COMPLETE를 확인한다.
10회 반복하려면 새 결과 경로를 지정하고 `--repeats 10`으로 바꾼다.
`--smoke`는 64 MiB·3초·ramp 0·1회로 줄이는 기능 검사이며 본 측정과 구별된다.
읽기 전용 대조를 추가할 때는 위 명령에 `--workloads randrw randread`를 추가한다.
**randread만 선택해도 사전 초기화는 쓰기를 수행한다.**

4. 실제 결과로 그래프를 만든다.

```bash
./sudo_exec.sh experiments/plot_fig5.py "$FIG5_RESULT"
```

`fio-comparison-randrw.png`, `.pdf`, `.svg`, `fio-comparison.csv`가 생성된다.
randread를 추가했다면 해당 workload의 그림도 생긴다. 그래프는 IOPS, 읽기·쓰기
p99 완료 지연, 선택 CPU들의 관측 사용량을 표시한다. DBMS TPS와 섞으면 실행기가 거부한다.

## 결과를 확인하는 순서

1. `run.json`의 `status`와 `summary.csv`의 모든 `status`가 성공인지 본다.
   fio 종료 코드가 0이어도 JSON의 job error, I/O 누락, 지나치게 짧은 측정은 실패다.
   실패·타임아웃의 JSON과 로그를 남기며 불완전한 반복 그룹에는 그래프 막대를 만들지 않는다.
2. IOPoll이 느리면 해당 폴더의 `fio.json`에서 `iodepth_level`, `read`/`write`의 IOPS,
   `clat_ns`, CPU 사용량을 함께 확인한다. 설정 QD 128과 실제 깊이를 구분한다.
3. `*_iops.log`로 시간에 따라 처리량이 유지되는지 확인한다.
   `job.fio`와 `command.json`은 실제 장치·엔진·옵션을 검증할 근거다.
4. `host-samples.json`에는 구성 시작/종료의 `/proc/stat`과 접근 가능한 NVMe 온도를 보존한다.
   `selected_cpu_cores`는 CPU 24와 25의 busy 비율 합이다. SQPoll을 포함하도록 모든 구성에서
   동일한 CPU 집합을 관측하지만 다른 프로세스와 시작·ramp 시간도 포함된다.
   fio 자체의 `usr_cpu + sys_cpu`는 SQPoll 스레드 전체의 사용량이 아니다.
5. 1회 측정은 실행 경로와 산출물의 기능 검증이다. 변동성이나 논문과 같은 성능 경향을
   입증하려면 동일 조건의 반복 측정이 필요하다. IOPS를 DBMS TPS로 환산하지 않는다.

파일 모드에서는 앞의 6개 구성만 실행된다. 나머지는 raw 전용으로 표시된다.
파일 모드는 새 전용 데이터 파일만 생성하고, 전체 성공 시 그 파일만 지운다.
실패 시 데이터 파일과 로그를 남긴다.

## 선택 사항: 저장소의 fio 소스로 빌드

기본 경로에는 필요 없다. 저장소 스냅샷을 명시적으로 비교할 때만 사용한다.

```bash
python3 experiments/build_fig5_fio.py --jobs 16
# fio 실행 옵션에 --fio 대신 --build-dir "$PWD/build-fig5-fio" 지정
```

`fio/` 스냅샷은 fio-3.39를 표시하며, Git 추적 파일을 별도 빌드 폴더로 복사한다.
원본 스냅샷에서 Makefile이 누락되어
[공식 fio-3.39 Makefile](https://github.com/axboe/fio/blob/fio-3.39/Makefile)을
`experiments/fio-v3.39.Makefile`에 그대로 보관했다.
SHA-256은 `b909650cfbb188f2ba2b2dc7082af6f507c10c276b05fcdc97d848dfd84121c3`이다.
C 언어 모드는 gnu99로 지정하고 컴파일러·소스·바이너리 해시를 기록한다.
이 스냅샷 빌드는 설치된 fio 3.42와 별개의 실행 조건이다.
