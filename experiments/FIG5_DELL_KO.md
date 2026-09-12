DELL에서 그림 5의 파일 기반 실험 실행하기

**추가 구현 안내:** `--storage raw-nvme`로 마지막 세 항목을 포함한 전체 열 항목을 실행하는 기능을 추가했다. 전용 namespace 준비, polling 설정과 명령은 [NVMe 전체 실험 안내](FIG5_NVME_KO.md)를 사용한다. 아래 내용은 기존 `file` 모드의 절차이며, 기본 실행 방식은 계속 일반 파일이다. 사용자의 `dell-20260911-131224` 결과에서는 파일 모드의 1천만 레코드·1 GiB 본 실험 7개 항목이 모두 성공했음을 이후 확인했다.

2026-09-11 기준으로 코드 수정과 DELL 현지 빌드를 완료했다. DELL의 `/mnt/nvme0n1p1`에 만든 일반 파일에서 **앞의 7개 항목 모두 작은 기능 검사에 성공**했다. 코드 반영 당시의 검사는 100,000개 레코드·4 MiB 버퍼 풀·항목당 로딩 후 3초 조건이었다. 이후 사용자가 실행한 `dell-20260911-131224`에서 10,000,000개 레코드·1 GiB 버퍼 풀의 본 실험도 7개 항목 모두 성공했다. 아래 명령으로 같은 파일 기반 실험을 다시 실행할 수 있다.

이번 실행기는 `/mnt/nvme0n1p1`의 ext4 파일에 `O_DIRECT` I/O를 수행한다. 논문의 마지막 `+Passthru`, `+IOPoll`, `+SQPoll` 세 항목은 NVMe namespace에 직접 명령을 보내는 누적 구성이다. 이 세 항목은 파일 방식으로 측정할 수 없으므로 CSV에는 `UNSUPPORTED`, 그래프에는 `N/A`로 표시한다. 따라서 이 결과는 **현재 DELL에서 앞의 7개 설계를 비교하는 재현**이며, 원본 raw 장치 실험의 열 개 막대 전체와 같은 I/O 경로는 아니다.

실험 코드는 DELL의 `/home/leedaeeun/Documents/github/vldb26-iouring`에 준비되어 있다. ThinkPad에도 같은 수정이 있다. 바이너리는 `-march=native`를 사용하므로 각 컴퓨터에서 따로 빌드해야 한다. DELL의 실제 hostname은 `arch`이며 기본 결과 경로에도 이 이름이 사용된다.

| 파일 | 하는 일 |
|---|---|
| [build_fig5.py](build_fig5.py) | 고정 liburing 준비, 두 백엔드 빌드, 빌드 식별 정보 저장 |
| [run_fig5_local.py](run_fig5_local.py) | 사전 점검, 파일 모드 7개/raw 모드 10개 항목 실행, 로그·CSV·실행 환경 수집 |
| [plot_fig5_local.py](plot_fig5_local.py) | 새 측정값으로 PNG·PDF·SVG와 집계 CSV 생성 |
| [fig5_common.py](fig5_common.py) | 그림 5의 설정 행렬과 소스·바이너리 식별 공통 함수 |
| [fig5_nvme.py](fig5_nvme.py) | raw 장치 식별·사용 상태·polling·CPU 점검과 독점 사용 |
| [test_fig5_local.py](tests/test_fig5_local.py) | 파일 보존, 실패·타임아웃·통계·집계 동작 검증 |
| [test_fig5_nvme.py](tests/test_fig5_nvme.py) | raw 장치 보호, 실행 경로, SQPoll CPU, 완료 상태와 집계 검증 |

기존 `bench_buffer_mgr.py`의 원격 서버 구성이나 R 스크립트를 수정할 필요 없이 위 도구를 사용한다. 이번에 추가한 실행기는 distexprunner를 사용하지 않는다.

**1. DELL에 접속하고 저장소로 이동한다.**

ThinkPad 터미널에서 접속한다. 이후 안내한 빌드와 실행 명령은 DELL의 터미널에서 입력한다.

```bash
ssh leedaeeun@182.230.201.3 -p 3333
cd /home/leedaeeun/Documents/github/vldb26-iouring
```

DELL에 소스 복사와 빌드를 이미 해 두었다. 소스를 수정했거나 다른 컴퓨터에 준비할 때는 다음 빌드를 다시 수행한다. DELL 저장소는 현재 ThinkPad의 기준 커밋 `1b37a9013d5f528639e049a97f9752b258457590`에서 복사했고, 수정 사항은 아직 커밋하지 않았다.

**2. 필요한 패키지와 두 실행 파일을 준비한다.**

DELL에는 필요한 빌드·실행 패키지와 matplotlib가 설치되어 있다. 다른 Arch 계열 환경에서 설치가 필요하면 아래 명령을 사용한다.

```bash
sudo pacman -S --needed \
  base-devel git cmake pkgconf libaio numactl libnvme \
  python python-matplotlib

python3 experiments/build_fig5.py --jobs 8
```

빌드 도구는 `libs/liburing`만 HTTPS로 초기화하고 고정 커밋 `4ee26f88a0592675bf623b76e116124956a048ba`인지 검사한다. 시스템 liburing을 덮어쓰지 않고 프로젝트의 정적 라이브러리를 링크한다. Boost Fiber 1.89.0은 기존 CMake 설정이 다운로드한다. 처음 빌드할 때 인터넷 연결이 필요하다. PostgreSQL, vmcache, distexprunner 서브모듈과 Nix, R, fio는 이 실행 절차에 필요하지 않다.

성공하면 다음 파일이 생긴다.

```text
build-fig5/buffer_mgr            # POSIX 및 io_uring 항목
build-fig5/buffer_mgr_libaio     # libaio +Fibers 항목
build-fig5/fig5-build.json       # 소스/바이너리 해시, 컴파일러, 호스트, liburing 커밋
build-fig5/fig5-*.log            # 준비·구성·빌드 로그
```

실행기는 바이너리, 빌드 호스트, 소스 해시를 확인한다. 소스를 바꾼 뒤에는 `build_fig5.py`로 다시 빌드한다. 기존 `cmake --build`만 직접 실행하면 실행기용 빌드 정보가 갱신되지 않는다.

**3. 작은 기능 검사로 실행 경로를 확인한다.**

```bash
python3 experiments/run_fig5_local.py --smoke --preflight
python3 experiments/run_fig5_local.py --smoke
```

기본값은 데이터 경로 `/mnt/nvme0n1p1`, 예상 마운트 `/mnt/nvme0n1p1`, 작업 CPU 2, NUMA node 0이다. DELL에서는 CPU 2가 해당 NUMA node에 속함을 확인했다. 마운트가 빠져 데이터 경로가 다른 파일시스템으로 바뀌면 실행을 거부한다. `--preflight`는 마운트·공간·CPU·빌드·memlock 설정을 읽어서 검사하며, 데이터 파일을 만들거나 벤치마크 I/O를 실행하지 않는다.

`--smoke`는 100,000개 레코드, 4 MiB 버퍼 풀, 항목마다 128 MiB 파일, 로딩 후 3초를 사용한다. 데이터가 버퍼 풀보다 커서 읽기와 퇴거 쓰기를 함께 확인한다. 실제 프로그램 종료 코드가 0이고 로딩 이후 트랜잭션 통계와 읽기·쓰기가 관찰되어야 `PASS`다. 이 값은 논문의 본 실험 수치로 사용하지 않는다.

**4. 본 실험을 실행할 터미널의 memlock 한도를 올린다.**

`+RegBufs`는 1 GiB 버퍼 풀 전체를 등록한다. 확인 당시 DELL의 soft/hard memlock 한도는 모두 8 MiB였다. 아래 명령은 **현재 셸과 이후 그 셸에서 시작하는 프로세스**에 2 GiB 한도를 부여한다. 사용자 터미널에서 sudo 암호를 입력한다.

```bash
sudo prlimit --pid "$$" --memlock=2147483648:2147483648
prlimit --pid "$$" --memlock
python3 experiments/run_fig5_local.py --preflight
```

한도는 바이트 단위이며, 2 GiB를 즉시 할당한다는 뜻은 아니다. 본 실험의 버퍼 풀은 그대로 1 GiB다. 벤치마크는 일반 사용자로 실행한다. 새 SSH 접속이나 새 터미널에서는 위 한도를 다시 설정해야 한다. 설정은 커널 소스 수정이나 재부팅이 필요하지 않다. `--preflight`가 통과해도 실제 1 GiB 등록과 I/O 성공은 본 실험 로그와 종료 결과로 확인해야 한다.

**5. 원본 워크로드와 측정 시간으로 앞의 7개 항목을 실행한다.**

```bash
python3 experiments/run_fig5_local.py
```

실제 실행할 명령만 확인하려면 다음을 사용한다. 사전 점검은 동일하게 적용한다.

```bash
python3 experiments/run_fig5_local.py --dry-run
```

기본 본 실험 조건은 다음과 같다.

| 조건 | 값 |
|---|---|
| 레코드 / 키 / 값 | 10,000,000개 / 8바이트 / 128바이트 |
| 페이지 / 버퍼 풀 | 4 KiB / 1 GiB (`virt_size=1073741824`) |
| 워크로드 | 원본 코드의 uniform YCSB, `ycsb_read_ratio=0` |
| 작업 배치 | 트랜잭션 작업 스레드 CPU 2, 메모리 NUMA node 0; 통계 스레드 별도 |
| 측정 시간 | 항목별 로딩 완료 후 10,000 ms |
| 통계 출력 | 1,000,000 μs 간격 |
| 반복 | 항목별 1회 |
| 실험 파일 | 항목마다 새 8 GiB 일반 파일 |
| 시간 제한 | 항목별 데이터 로딩을 포함하여 900초 |

기본 순서는 아래와 같고, bool 인자는 실행기가 `true`/`false` 문자열로 전달한다. 여기서 128 fibers는 128개의 CPU나 작업 스레드를 뜻하지 않는다.

| 번호 | CLI의 case 이름 | 그림의 항목 | 주요 설정 |
|---|---|---|---|
| 1 | `posix` | Posix Sync. | concurrency 1, eviction batch 1, POSIX 동기 I/O |
| 2 | `uring_sync` | io_uring Sync. | concurrency 1, eviction batch 1, io_uring 동기 대기 |
| 3 | `batch_evict` | +BatchEvict | concurrency 1, eviction batch 128 |
| 4 | `libaio_fibers` | libaio +Fibers | concurrency 128, eviction batch 128, 즉시 제출, 별도 libaio 바이너리 |
| 5 | `uring_fibers` | io_uring +Fibers | concurrency 128, eviction batch 128, 즉시 제출 |
| 6 | `batch_submit` | +BatchSubmit | 5번 조건에서 제출 배치 활성화 |
| 7 | `regbufs` | +RegBufs | 6번 조건에 링·파일·버퍼 등록 모두 추가 |

일부 항목만 실행하거나 반복 실험을 추가할 수도 있다.

```bash
# 지원 항목 확인
python3 experiments/run_fig5_local.py --list-cases

# 제출 배치와 메모리 등록 항목만 다시 측정
python3 experiments/run_fig5_local.py --cases batch_submit regbufs

# 추가 실험: 각 항목 30초씩 3회, 반복마다 실행 순서 섞기
python3 experiments/run_fig5_local.py \
  --duration-ms 30000 --repeats 3 --order shuffle --seed 42
```

추가 실험은 원본의 10초·1회 결과와 구분한다. 로딩 시간이 전체 소요 시간에 더해지므로 7개 항목이 정확히 70초에 끝나는 것은 아니다. 한 항목이 실패해도 로그를 보존하고 다음 항목을 실행하며, 선택한 항목 중 실패가 있으면 실행기는 종료 코드 1을 반환한다. 사전 점검 실패는 종료 코드 2다. 통계·실험 파일을 보존하려면 SSH 연결이 유지되는 터미널에서 실행한다. 장시간 실험은 사용 중인 tmux/screen 세션 안에서 실행하면 연결 단절 영향을 줄일 수 있다.

**6. 출력된 결과 경로로 그래프를 만든다.**

실행 중 다음처럼 실제 디렉토리가 출력된다. 실행마다 새 경로가 생성된다.

```text
RESULT_DIR=/home/leedaeeun/Documents/github/vldb26-iouring/results/figure5/arch/실행ID
```

이 경로를 그대로 사용한다. 실행기 마지막 줄에도 완성된 플롯 명령이 출력된다.

```bash
# /실제/결과/디렉토리를 RESULT_DIR에 출력된 경로로 바꾼다.
python3 experiments/plot_fig5_local.py /실제/결과/디렉토리
```

원본 플롯처럼 각 실행의 **마지막 1초 통계 `tps`**를 기본 지표로 사용한다. 반복이 여러 번이면 각 실행의 마지막 값들을 모아 중앙값을 막대로, 최솟값~최댓값을 오차 막대로 표시한다. 전체 측정 시간 동안의 평균 TPS와는 다르다. 하나라도 실패하거나 빠진 반복이 있으면 해당 항목의 막대를 그리지 않고 `incomplete`와 성공 횟수를 표시한다.

보조 지표도 별도 파일로 만들 수 있다.

```bash
python3 experiments/plot_fig5_local.py /실제/결과/디렉토리 --metric mean
```

`mean`은 로딩 구간과 첫 번째 비영(非零) TPS 구간을 제외한 후 남은 통계 구간의 평균이다. 첫 비영 구간은 로딩과 트랜잭션 처리가 섞일 수 있고 I/O 카운터 초기화의 영향을 받을 수 있어 제외한다. 이는 원본의 마지막 샘플 지표를 대체하지 않으며, 정확한 전체 실행 시간으로 나눈 누적 TPS도 아니다.

| 결과 파일 | 내용 |
|---|---|
| `run.json` | 실행 조건, 순서, 상태, 호스트·커널·마운트·CPU·memlock·빌드 정보 |
| `r01-항목.command.json` | subprocess에 전달한 정확한 인자 배열 |
| `r01-항목.log` | 프로그램의 원본 stdout/stderr; 로딩 및 실패 원인 포함 |
| `samples.csv` | 로딩 구간을 포함한 파싱된 통계 샘플 전체 |
| `summary.csv` | 항목·반복별 상태, 마지막 TPS, 보조 평균, 종료 코드, I/O 카운터 |
| `figure5-last.png/.pdf/.svg` | 마지막 샘플 지표의 그래프 |
| `figure5-last.csv` | 반복별 결과를 집계한 중앙값·최솟값·최댓값 |
| `source.diff`, `fig5-build.json`, `compile_commands.json`, `CMakeCache.txt` | 기준 소스와 변경·빌드 조건 |
| `lscpu.txt`, `lsblk.json` | 실행 호스트의 CPU·저장장치 정보 |

데이터 파일은 `/mnt/nvme0n1p1/fig5-실행ID-임의문자열/`에 생성한다. 성공한 항목의 데이터 파일은 다음 항목 전에 삭제하고, 실패한 파일은 남긴다. B-tree 로더가 매번 새로 생성하는 파일이며 원시 측정 로그는 삭제하지 않는다. `--keep-data`를 주면 성공 파일도 보존하므로 기본 조건에서는 항목·반복마다 8 GiB가 추가로 필요하다. 이 옵션이 없는 정상 실행은 대략 한 파일의 공간을 사용한다. 동일한 데이터 경로에서 실행기 두 개가 동시에 측정하는 것은 잠금으로 차단한다.

**7. 확인된 수정·검증 범위를 이해한다.**

이번 수정에서는 [루트 CMake](../CMakeLists.txt)의 AVX-512 강제 옵션을 제거하고, [버퍼 매니저 빌드](../src/buffer_mgr/CMakeLists.txt)와 [Reactor 선택](../src/buffer_mgr/kuring.hpp)을 변경했다. libaio와 io_uring의 공통 소스도 백엔드별로 따로 컴파일한다. GCC 16에서 실제로 발생한 컴파일 오류에 맞춰 `nostd.hpp`의 `<cstdint>`, `stats_printer.hpp`의 `<mutex>`, `hugepages.cpp`의 `<unistd.h>`를 추가했다. 커널 소스, 부팅 설정, 파티션 구성은 변경하지 않았다.

2026-09-11 검증 결과는 다음과 같다.

| 검증 | ThinkPad | DELL |
|---|---|---|
| GCC 16.2.1, Release, 두 백엔드 빌드 | 성공 | 성공 |
| 7개 항목, 100,000개 레코드, 4 MiB 버퍼 풀, 로딩 후 3초 | 7/7 PASS | 7/7 PASS |
| 실제 읽기·퇴거 쓰기·TPS 통계 | 각 항목에서 확인 | 각 항목에서 확인 |
| 링·파일·4 MiB 버퍼 등록 항목 | 성공 | 성공 |
| CSV → PNG/PDF/SVG 플롯 | 성공 | 성공 |
| 10,000,000개 레코드·1 GiB 본 실험 | 미실행 | 사용자 실행 결과 7/7 PASS (`dell-20260911-131224`, raw 기능 추가 전 빌드) |
| 전체 raw NVMe / IOPoll / SQPoll 항목 | 미실행 | 미실행 |

DELL의 기능 검사 증거는 저장소의 `results/figure5/dell-validation-smoke-01/`에 있다. 예를 들어 DELL에서 아래 명령으로 이미 생성된 기능 검사 그래프를 다시 만들 수 있다.

```bash
python3 experiments/plot_fig5_local.py results/figure5/dell-validation-smoke-01
python3 -m unittest discover -s experiments/tests -p 'test_fig5*.py' -v
```

논문 설명은 100% 업데이트지만 원본 `ycsb_workload.hpp`는 `rnd <= read_ratio` 경계를 사용한다. `[0,100)` 난수에서 `read_ratio=0`이면 소스상 약 1% 읽기·99% 업데이트가 된다. 이번에는 원본 아티팩트와 조건을 맞추기 위해 이 동작을 유지했고 실행 기록에도 남긴다. 기록의 `reads`/`writes`는 SSD 페이지 I/O 카운터이며 이 트랜잭션 비율을 직접 계측한 값은 아니다.

마지막 세 항목은 별도 [raw-nvme 모드](FIG5_NVME_KO.md)에서 지원한다. 직접 쓰기가 가능한 전용 NVMe namespace와 polling queue 구성이 필요하다. 마운트된 장치의 사용은 차단한다. 일반 파일 위에서 SQPoll만 켠 결과를 원본의 마지막 누적 막대로 표시하지 않는다. 원본 `script/reset_ssds.sh`, `script/write_ssds.sh`는 이 파일 기반 절차에 사용하지 않는다.

ThinkPad에서 같은 실행기를 사용할 때는 그 호스트의 데이터 디렉토리와 실제 마운트를 모두 명시한다. 예를 들어 현재 저장소가 ext4 루트 파일시스템에 있다면, 사용자 권한으로 만든 전용 디렉토리에 다음처럼 실행할 수 있다.

```bash
mkdir -p results/figure5/thinkpad-data
python3 experiments/run_fig5_local.py --smoke \
  --data-root "$PWD/results/figure5/thinkpad-data" --expected-mount / \
  --cpu 2 --numa-node 0
```

두 호스트의 비교 그래프는 같은 모드·레코드 수·버퍼 풀·측정 시간의 결과 디렉토리를 한 컴퓨터로 복사한 후 생성한다. 각 패널의 배율은 해당 호스트의 POSIX 기준값으로 계산하고 y축 범위는 공통으로 맞춘다.

```bash
python3 experiments/plot_fig5_local.py \
  /결과/thinkpad /결과/dell --output-prefix results/figure5/comparison
```
