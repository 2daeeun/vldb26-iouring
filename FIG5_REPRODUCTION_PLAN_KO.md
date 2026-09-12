그림 5의 ThinkPad·DELL 재현 가능성 및 실행 절차

**추가 구현:** 마지막 세 항목을 포함하는 `raw-nvme` 모드를 양쪽 컴퓨터에 추가했다. 현재 마운트된 NVMe에서는 실행을 차단하며, 전용 namespace와 polling 설정을 준비해야 한다. 최신 내용은 [NVMe 전체 실험 안내](experiments/FIG5_NVME_KO.md)를 사용한다. DELL의 `dell-20260911-131224` 결과에서 파일 기반 본 실험 7개 항목의 성공을 확인했으며, raw 세 항목의 실제 I/O·성능은 아직 측정하지 않았다.

**2026-09-11 구현 후 안내:** DELL의 `/mnt/nvme0n1p1` 일반 파일에서 앞의 7개 항목을 실행하는 도구를 구현했다. ThinkPad와 DELL에서 두 백엔드를 빌드했고, 각각 7개 항목의 작은 기능 검사와 그래프 생성을 확인했다. 최신 명령과 검증 범위는 [DELL 실행 안내](experiments/FIG5_DELL_KO.md)를 사용한다. 아래 본문은 구현 이전의 조사·계획 기록이며, “아직 생성하지 않았다/수정해야 한다”는 표현은 당시 상태다. 1천만 레코드·1 GiB 본 실험과 마지막 raw NVMe 세 항목은 아직 실행하지 않았다.

2026-09-10에 저장소의 논문 PDF, 실험 코드, 공개 측정 데이터와 ThinkPad를 확인했다. 이후 사용자가 제공한 SSH 주소로 DELL에도 접속해 환경과 작은 io_uring 등록 검사를 확인했다. 2026-09-11에는 사용자 지정에 따라 DELL의 실험 데이터 경로를 `/mnt/nvme0n1p1`로 확정하고 해당 마운트와 의존성 설치 상태를 다시 확인했다. 현재 소스 기준점은 `1b37a9013d5f528639e049a97f9752b258457590`이다. 전체 비교 대상은 ThinkPad와 DELL이며, 이번 설치·빌드 준비의 우선 대상은 DELL이다. 아래에서 첫 번째 하드웨어 표는 9월 10일 ThinkPad 값이고, 두 번째 표의 DELL 저장장치·패키지 값은 9월 11일 재확인 결과다.

ThinkPad와 DELL 모두 그림 5의 실험 방법을 적용할 하드웨어 용량과 기본 io_uring 기능이 있다. 두 컴퓨터 비교의 첫 목표는 NVMe의 파일시스템 위에 만든 일반 파일에 직접 I/O를 수행하는 방식으로 앞의 7개 막대를 각각 측정하는 것으로 잡는다. 이를 위해 빌드 설정, CPU 지정, libaio 빌드, 메모리 등록 한도를 준비해야 한다. 이 경로의 DBMS 실행 성공 여부와 처리량은 아직 측정하지 않았다.

마지막 3개 막대까지 원본과 같은 NVMe passthrough 경로로 실행하려면, namespace에 직접 쓰기를 해도 되는 실험용 NVMe SSD 또는 독립된 미사용 NVMe namespace가 필요하다. ThinkPad의 NVMe namespace는 운영체제, swap, 사용자 데이터에 사용 중이다. DELL은 운영체제가 SATA SSD에 있지만 NVMe는 현재 `/mnt/nvme0n1p1`에 마운트된 ext4로 사용한다. 이 마운트 경로 안에 파일을 만드는 실험과 `/dev/ng0n1`에 원본 NVMe 명령으로 직접 쓰는 실험은 다르다. 후자는 마운트된 파일시스템과 데이터를 손상시킬 수 있으므로, 마운트 경로를 지정했다는 이유로 실행해서는 안 된다.

논문과 같은 처리량 수치나 개선 배율은 보장할 수 없다. CPU, SSD, 커널과 I/O 대상이 다르므로, 목표는 같은 워크로드와 단계별 설계 변경을 현재 컴퓨터에서 측정하고 차이를 설명하는 것이다.

논문의 그림 5는 로컬 PDF의 4쪽에 있다. 저장소에는 이미 [원본 그림 PDF](experiments/out/plot_buffer_mgr.pdf)와 [측정 CSV](experiments/data/bench_buffer_mgr.csv)가 들어 있다. 이 파일을 다시 그리는 작업과 현재 컴퓨터에서 새로 벤치마크를 실행하는 작업은 별개의 결과다. 저자의 공개 아티팩트는 [mjasny/vldb26-iouring](https://github.com/mjasny/vldb26-iouring)이다.

그림 5는 자체 구현한 B-tree와 버퍼 매니저에서 YCSB 계열 트랜잭션 처리량을 비교한다. 페이지가 메모리에 없으면 SSD에서 읽고, 공간이 부족하면 변경된 페이지를 SSD로 내보낸다. I/O가 끝날 때까지 기다리는 방식에서 시작해, 여러 트랜잭션을 겹쳐 실행하고 요청을 모아 제출하면서 성능이 어떻게 달라지는지 측정한다. 실행 대상은 `buffer_mgr`이며, fio나 PostgreSQL을 실행할 필요는 없다.

| 조건 | 그림 5의 설정과 의미 |
|---|---|
| 워크로드 | 논문 설명은 uniform 100% updates, 트랜잭션당 한 번의 업데이트 |
| 데이터 | 10,000,000개 레코드, 8바이트 키, 128바이트 값 |
| 페이지 크기 | 4 KiB |
| 버퍼 풀 | 코드의 `virt_size=1073741824`, 즉 1 GiB |
| 메모리 부족 조건 | 전체 데이터와 인덱스가 버퍼 풀보다 커서 저장장치 I/O가 발생 |
| 동시성 | 동기형은 1, 비동기형은 최대 128 fibers |
| 작업 코어 | 트랜잭션/I/O 처리용 1코어; 마지막 SQPoll 항목은 추가 코어 사용 |
| 측정 시간 | 원본 YCSB 설정은 로딩 완료 후 10,000 ms |
| 반복 및 집계 | 제공 CSV의 해당 실험은 `run=0`; 원본 플롯은 설정별 마지막 `tps` 샘플 사용 |

Fiber는 하나의 작업 스레드에서 번갈아 실행되는 사용자 공간 실행 단위다. 여기서 `concurrency=128`은 작업 스레드나 CPU 128개를 의미하지 않는다. 따라서 논문의 96코어 서버나 768 GiB RAM 전체가 그림 5에 필요한 것은 아니다. 실험 스크립트도 `ssd_id=[0]`으로 SSD 하나만 선택한다.

논문 본문은 기본 실험 커널을 6.15.0으로 설명하지만, 그림 5 수치에 대응하는 제공 CSV에는 `kernel=6.15.0-rc7`이 기록되어 있다. 재현 기록에는 이 차이도 남겨야 한다. 설정과 데이터의 근거는 [bench_buffer_mgr.py](experiments/bench_buffer_mgr.py), [plot_buffer_mgr.R](experiments/plot_buffer_mgr.R), [config.hpp](src/buffer_mgr/config.hpp), [buffer_mgr.cpp](src/buffer_mgr/buffer_mgr.cpp)이다.

원본 그림의 막대와 제공 CSV의 수치는 다음과 같이 대응한다. 아래 수치는 현재 컴퓨터의 측정값이 아니다.

| 순서 | 그림의 막대 | 핵심 변화 | 원본 tx/s | 현재 컴퓨터에서의 진행 조건 |
|---|---|---|---:|---|
| 1 | Posix Sync. | `pread`/`pwrite` 기반 동기 실행 | 16,465 | 준비 후 일반 파일로 측정 가능성 확인 |
| 2 | io_uring Sync. | 요청 하나를 제출하고 완료 대기 | 16,549 | 준비 후 일반 파일로 측정 가능성 확인 |
| 3 | io_uring +BatchEvict | 동기 실행에서 퇴거 쓰기를 모아서 제출 | 19,064 | 준비 후 일반 파일로 측정 가능성 확인 |
| 4 | libaio +Fibers | libaio와 128 fibers | 173,001 | libaio용 별도 빌드 필요 |
| 5 | io_uring +Fibers | io_uring과 128 fibers | 183,472 | 준비 후 일반 파일로 측정 가능성 확인 |
| 6 | +BatchSubmit | 읽기 요청 제출도 묶음 처리 | 216,608 | 준비 후 일반 파일로 측정 가능성 확인 |
| 7 | +RegBufs | 버퍼·파일·링 등록 활성화 | 237,778 | 1 GiB 버퍼를 등록할 수 있는 memlock 한도 필요 |
| 8 | +Passthru | NVMe 명령을 namespace에 직접 제출 | 300,491 | 실험용 NVMe 장치/namespace 필요 |
| 9 | +IOPoll | 앞의 최적화에 완료 polling 추가 | 376,395 | 위 장치와 NVMe poll queue 설정 필요 |
| 10 | +SQPoll | IOPoll을 유지하고 제출 polling 스레드 추가 | 546,501 | 위 조건과 별도 물리 코어 배치 필요 |

8번 이후는 파일시스템 파일 대신 `/dev/ng…`라는 NVMe namespace 문자 장치를 사용한다. 이는 [config.cpp](src/buffer_mgr/config.cpp)의 경로 검사와 [nvme.hpp](src/utils/nvme.hpp)의 NVMe 명령 구성으로 확인했다. 현재의 `/dev/ng0n1`은 운영체제가 사용하는 `/dev/nvme0n1`과 같은 namespace다. `/mnt/nvme0n1p4`가 별도 파티션이라는 이유로 그 namespace에 직접 쓰기를 해도 되는 것은 아니다.

일반 파일에서 SQPoll을 별도로 실험하는 것은 가능성을 검토할 수 있다. 다만 그림 5의 마지막 막대는 passthrough와 IOPoll까지 누적한 설정이므로, 파일 기반 SQPoll 결과를 그 막대의 동일 조건 재현이라고 표시해서는 안 된다.

ThinkPad의 읽기 전용 점검 결과는 다음과 같다. 여유 공간, 전원 상태와 소프트웨어 버전은 점검 시점의 값이다.

| 항목 | 확인 결과 | 재현에 미치는 영향 |
|---|---|---|
| CPU | Intel Core i7-1370P, 14코어/20 논리 CPU | 작업용 P-core를 지정해 실행 가능 |
| 명령어 | AVX2 지원, AVX-512 미지원 | 원본의 AVX-512 강제 옵션 제거 필요 |
| 메모리 | 약 15 GiB 표시 | 1 GiB 버퍼 풀과 부가 구조를 실행할 용량은 있어 보임; 실제 최대 사용량은 실행 시 측정 |
| SSD | KIOXIA KBG5AZNT1T02, 약 954 GiB, namespace 1개 | 논문의 CM7-R과 다른 장치이며 현재 사용 중 |
| 루트 파일시스템 | ext4, 가용 약 339 GiB | 새 실험 전용 일반 파일을 만들 공간 있음 |
| 추가 마운트 | `/mnt/nvme0n1p4`, ext4, 가용 약 97 GiB | 같은 SSD의 기존 데이터 파티션 |
| OS | EndeavourOS, Arch 계열 | Ubuntu용 패키지 명령을 그대로 사용하지 않음 |
| 커널 | `6.19.14-ExtFUSE-AllOpt` | 현재 커널에서 기본 io_uring 기능 확인; 논문과의 버전 차이 기록 필요 |
| io_uring 차단 | `kernel.io_uring_disabled=0` | 시스템 차원의 비활성화 상태 아님 |
| NVMe polling | `nvme.poll_queues=0`, `queue/io_poll=0` | 현재 장치 설정은 그림의 IOPoll 실험 준비가 안 되어 있음 |
| memlock 한도 | soft/hard 모두 8 MiB | 1 GiB 등록 버퍼 실험에 부족 |
| 전원 | AC online=0, governor=`powersave` | 성능 실험 전 AC 연결 및 전력 조건 고정 필요 |
| 빌드 도구 | GCC 16.2.1, CMake 4.4.3 | 논문 도구 버전과 다르며 실제 빌드는 별도 검증 필요 |
| 시스템 라이브러리 | liburing 2.15, libaio, libnuma, libnvme 및 필요한 시스템 헤더 확인 | 저장소가 지정하는 liburing과 동일하다고 간주하면 안 됨 |
| 저장소 liburing | 서브모듈 미초기화 | 지정 커밋을 가져오고 configure 수행 필요 |
| Boost | CMake는 Boost 1.89.0을 다운로드하도록 구성 | 시스템의 boost-libs 설치만으로 빌드 준비가 끝났다고 볼 수 없음 |
| 그림 도구 | Rscript와 pdfcrop 있음, 플롯에 필요한 11개 R 패키지는 없음 | R 의존성 설치 또는 별도 Python 플롯 필요 |

DELL은 사용자가 부팅을 알린 뒤 약 2분 기다려 `ssh leedaeeun@182.230.201.3 -p 3333`으로 접속했다. SSH 접속은 성공했으며, 호스트 이름은 `arch`, DMI 모델은 `Dell Inc. Precision Tower 7910`으로 확인했다. 아래 값은 해당 SSH 세션에서 확인한 값이다.

| 두 컴퓨터의 비교 항목 | ThinkPad | DELL |
|---|---|---|
| 실제 호스트 확인 | `thinkpad` | `arch`, Dell Precision Tower 7910 |
| CPU 및 물리 코어 배치 | i7-1370P, 14코어/20 논리 CPU, P/E-core 및 SMT | Xeon E5-2699 v4 2개, 44코어/88 논리 CPU, NUMA 2개 |
| 명령어 | AVX2 지원, AVX-512 미지원 | AVX2 지원, AVX-512 미지원 |
| 메모리 | 약 15 GiB | 약 62 GiB, 점검 시 가용 약 60 GiB |
| 커널 | `6.19.14-ExtFUSE-AllOpt` 빌드 #28 | `6.19.14-ExtFUSE-AllOpt` 빌드 #27 |
| 기본 io_uring | 작은 링/등록 검사 성공 | 같은 검사 소스로 작은 링/등록 검사 성공 |
| NVMe 장치 | KIOXIA KBG5AZNT1T02, namespace 하나 | Samsung SSD 970 EVO Plus 1TB, namespace 하나 |
| NVMe의 현재 사용 | 운영체제, swap, 데이터 | NVMe 전체 용량의 ext4 파티션 하나가 `/mnt/nvme0n1p1`에 마운트됨 |
| 운영체제 파일시스템 | NVMe 위 ext4 | Samsung SSD 870 EVO의 `/dev/sdb1` 위 ext4 |
| 일반 파일 실험 대상 | NVMe의 ext4 위 새 전용 파일 | 사용자 지정 `/mnt/nvme0n1p1` 아래 새 전용 파일, ext4 용량 약 916 GiB, 가용 약 870 GiB, 사용자 쓰기 권한 있음 |
| 1 GiB 메모리 등록 | soft/hard 8 MiB 한도 조정 필요 | SSH 세션 soft/hard 8 MiB 한도 조정 필요 |
| NVMe polling queue | 현재 0개, `queue/io_poll=0` | 현재 0개, `queue/io_poll=0` |
| CPU governor | 점검 시 `powersave` | 점검 시 `performance` |
| 빌드·I/O 라이브러리 | GCC 16.2.1, CMake 4.4.3, 시스템 liburing 2.15 및 libaio/libnuma/libnvme 헤더 있음 | GCC 16.2.1 계열, CMake 4.4.3, 시스템 liburing 2.15 및 libaio/libnuma/libnvme 헤더 있음 |
| 저장소 위치 | `/home/leedaeeun/Documents/github/vldb26-iouring` 존재 | 같은 경로에는 저장소 없음; 설치 위치와 기준 커밋 준비 필요 |
| 플롯 도구 | matplotlib 있음, R 패키지 준비 필요 | matplotlib/pandas 있음, Rscript/pdfcrop/Nix는 없음 |
| 본 실험 결과 | 미실행 | 미실행 |

2026-09-11 재확인에서는 NVMe 구성이 이전 조회와 달라져 `/dev/nvme0n1p1` 하나만 존재하며 `/mnt/nvme0n1p1`에 마운트되어 있다. `findmnt`의 파일시스템은 ext4, 옵션은 `rw,nosuid,nodev,relatime`이다. 이전 문서의 `/mnt/nvme0n1p3` 실험 경로 제안은 사용자 지정과 최신 조회 결과에 따라 폐기한다. 이번 점검에서 파티션 변경, 포맷, 마운트 변경이나 실험 파일 생성을 수행하지 않았다.

DELL에서는 홈 디렉토리 아래에 데이터 파일을 만들면 운영체제용 SATA SSD를 측정하게 된다. DELL의 데이터 경로는 사용자 지정에 따라 `/mnt/nvme0n1p1` 아래의 새 전용 디렉토리로 명시한다. 예를 들어 `/mnt/nvme0n1p1/fig5/data.bin`을 새 실험 파일 경로로 사용할 수 있다. 바이너리와 로그는 운영체제 파일시스템에 두어도 되지만 `--ssd`가 가리키는 실험 데이터 파일의 실제 장치를 확인해야 한다.

**DELL에서 그림 5만 실행하기 위한 서브모듈과 의존성은 다음과 같다.** 현재 CMake 구성과 로컬 실행기·Python 플롯을 준비하는 방식을 기준으로 한다. DELL의 `/home/leedaeeun/Documents/github/vldb26-iouring`에는 아직 메인 저장소가 없으므로, 먼저 동일한 소스 기준점과 수정 내용을 준비해야 한다.

| 서브모듈 | 그림 5에서의 필요 여부 | 이유 |
|---|---|---|
| `libs/liburing` | 필수 | CMake가 이 경로의 헤더와 `src/liburing.a`를 직접 사용 |
| `distexprunner` | 저자 분산 실행 스크립트를 유지할 때만 필요 | 로컬 바이너리를 직접 실행하는 전용 실행기로 바꾸면 필요 없음 |
| `vmcache` | 불필요 | 그림 5의 `buffer_mgr` 실행 대상이 아님 |
| `postgresql` | 불필요 | 별도 PostgreSQL 실험용 |

| 구성 요소 | 용도 | 2026-09-11 DELL 상태 |
|---|---|---|
| `base-devel`, `git`, `cmake`, `pkgconf` | GCC/G++, Make, binutils 및 빌드·소스 준비 | 설치됨 |
| `libaio` | libaio 비교 경로와 `libaio.h` | 설치됨, 0.3.113 |
| `numactl` | `libnuma`, NUMA/CPU 배치와 `numa.h` | 설치됨, 2.0.19 |
| `libnvme` | `nvme/types.h`의 타입·상수 정의 | 설치됨, 1.16.2; 현재 소스는 passthrough를 꺼도 해당 헤더를 포함 |
| 프로젝트의 liburing | io_uring 빌드 의존성 | 메인 저장소를 준비한 뒤 지정 서브모듈 초기화 필요 |
| 시스템 `liburing` | 현재 작은 기능 검사 등에 사용 | 2.15 설치됨; 현재 CMake의 프로젝트 liburing 경로를 대체하지 않음 |
| Boost 1.89.0 | Fiber/Context 헤더와 라이브러리 | CMake FetchContent가 다운로드하고 빌드하도록 지정됨 |
| `python`, `python-matplotlib` | 준비할 로컬 실행기 및 그래프 생성 | 설치됨; pandas도 있지만 CSV 수집의 필수 조건으로 삼을 필요는 없음 |

시스템 `boost` 개발 패키지는 설치되어 있지 않고 `boost-libs` 1.92.0만 설치되어 있다. 그러나 현재 프로젝트는 Boost 1.89.0 소스를 CMake에서 직접 받아 빌드하므로 시스템 `boost` 설치를 필수로 추가할 필요는 없다. 최초 CMake 구성 시 다운로드가 가능한 네트워크가 필요하다. `libnvme`와 장치 진단 명령을 제공하는 `nvme-cli`는 다른 패키지이며, `buffer_mgr`의 컴파일에는 전자의 헤더가 필요하다. `nvme-cli`는 장치 진단을 추가할 때 선택적으로 준비할 수 있다.

아래 명령은 필요한 시스템 패키지를 준비하는 명령이다. 이번 조회에서 이 목록은 모두 설치되어 있으므로 당장 새로 설치해야 하는 항목은 없다. 패키지 설치나 업그레이드를 이번 점검에서 실행하지 않았다.

```bash
sudo pacman -S --needed \
  base-devel git cmake pkgconf \
  libaio numactl libnvme \
  python python-matplotlib
```

DELL에 메인 저장소를 준비한 뒤, 그 저장소 루트에서 필요한 liburing 서브모듈만 초기화하는 명령은 다음과 같다. `.gitmodules`에 GitHub SSH 주소가 들어 있으므로 명령 한 번에만 적용되는 HTTPS 주소를 지정한다. 사용자 전체의 Git 설정은 바꾸지 않는다.

```bash
git -c submodule.liburing.url=https://github.com/axboe/liburing.git \
  submodule update --init --recursive -- libs/liburing

git -C libs/liburing rev-parse HEAD

(cd libs/liburing && ./configure --cc=gcc --cxx=g++)
```

현재 저장소 기준의 liburing 커밋은 `4ee26f88a0592675bf623b76e116124956a048ba`이다. configure 절차는 [해당 커밋의 공식 README](https://github.com/axboe/liburing/blob/4ee26f88a0592675bf623b76e116124956a048ba/README)와 대조했다. 이 버전의 Makefile도 설정 파일이 없으면 configure를 실행하므로 수동 configure가 유일한 준비 방법인 것은 아니다. 위 명령은 사용할 컴파일러를 명시해 설정을 먼저 생성하는 방법이다. 프로젝트는 이 소스 트리의 정적 라이브러리를 링크하므로 `sudo make install`로 시스템 liburing을 덮어쓸 필요는 없다. 이후 AVX-512 옵션과 libaio 빌드 분리를 수정하고, CMake는 `Unix Makefiles` 생성기로 구성해 `buffer_mgr` 관련 타깃만 빌드한다. 현재 외부 liburing 빌드 명령이 `$(MAKE)`를 사용하므로 불필요하게 Ninja 생성기를 추가하지 않는다.

원본 R 플롯을 그대로 실행하려면 R, ggplot2/dplyr/sqldf/stringr/viridis/scales/tidyr/patchwork/forcats/ggpattern/ggh4x 및 pdfcrop 의존성을 추가로 준비해야 한다. 그림 5의 로컬 결과를 이미 설치된 matplotlib로 그리도록 수정하면 이 추가 설치는 필요 없다. Nix도 이 로컬 실행·플롯 구성의 필수 조건은 아니다.

DELL의 NVMe는 NUMA node 0에 연결되어 있다. 예를 들어 CPU 2와 3은 node 0의 서로 다른 물리 코어이므로 작업 스레드와 SQPoll 후보로 쓸 수 있다. CPU 0/44, 1/45는 각각 같은 물리 코어의 SMT 형제다. 실제 실행 시 CPU·메모리의 NUMA 배치를 함께 고정하고 기록한다. ThinkPad의 CPU 2/3은 같은 물리 코어라는 점과 다르므로 숫자가 연속한다고 같은 배치 정책으로 처리해서는 안 된다.

두 호스트의 커널 release 문자열은 같지만 빌드 번호와 시간이 다르다. 따라서 동일 커널 소스·설정·패치를 실행 중이라고 단정하지 않는다. 정식 비교 전에 각 커널의 빌드 출처를 기록하고, 커널 차이가 남으면 호스트별 조건 차이로 명시한다. 이번 점검에서 커널 설치나 재부팅을 수행하지 않았다.

공통 실행기는 두 호스트에서 같은 실험 행렬을 사용하되, 저장 경로, 작업 CPU, SQPoll CPU, 빌드 병렬도 같은 환경 값만 별도 설정으로 받도록 준비한다. 디스크 경로는 `thinkpad`나 `dell`이라는 이름으로 추정하지 않고 명시적으로 지정하고 검증한다. 두 호스트의 결과는 예를 들어 `results/figure5/<실제-hostname>/<실행-id>/` 아래에 각각 보관하고 원본 `experiments/data/`에는 섞지 않는다. 이 경로와 실행기는 구현 계획이며 이번 점검에서 생성한 것은 아니다.

두 컴퓨터 모두 데이터 1,000만 건, 버퍼 풀 1 GiB, 페이지 4 KiB, 동시성 1/128, 배치 1/128 조건을 유지한다. 각 컴퓨터의 코어 수에 비례해 concurrency나 버퍼 풀을 늘리면 같은 그림 5 워크로드 비교가 되지 않는다. 양쪽에서 같은 소스 및 liburing 커밋과 가능한 한 같은 컴파일러 버전을 사용하고, 바이너리는 각 컴퓨터에서 따로 빌드한다. `-march=native`를 사용하면 생성 명령어가 CPU별로 달라질 수 있으므로 실제 플래그를 기록하고 바이너리를 두 컴퓨터 사이에서 그대로 재사용하지 않는다.

플롯은 ThinkPad와 DELL을 별도 패널로 표시하고, 각 호스트의 절대 TPS와 동일 호스트 기준 개선 배율을 함께 제시한다. 한 컴퓨터의 `+RegBufs`를 다른 컴퓨터의 `+BatchSubmit`과 연결해 개선 효과를 계산하면 안 된다. 전체 10개 항목을 실행할 수 있는 호스트가 한쪽뿐이라면, 공통 7개 항목 비교와 그 호스트의 전체 10개 항목 결과를 각각 표시한다. 두 호스트 모두 전체 10개 항목을 원본 경로로 비교하려면 각 호스트에 적합한 실험용 NVMe 장치/namespace와 polling 설정이 필요하다.

커널 기능은 두 컴퓨터에서 시스템 liburing으로 같은 작은 C 프로그램을 빌드해 실제 확인했다. 이 프로그램은 저장장치나 데이터 파일을 열지 않고, 그림 5 코드와 같은 주요 플래그로 링을 만든 후 등록 API만 호출했다. 두 컴퓨터에서 아래 결과가 동일하게 나왔다.

```text
figure5_ring_setup=0 sq=4096 cq=65536
register_ring_fd=1
register_sparse_files=0
register_4KiB_buffer=0
```

각 API의 성공 반환값을 확인했다. 요청한 CQ 크기는 131072였으며 `CLAMP`에 의해 실제 크기는 65536이었다. 이 검사는 링 생성과 소규모 등록 성공만 입증한다. 저장소 liburing 빌드, 1 GiB 등록, DBMS 실행, NVMe I/O, IOPoll, 성능은 이 검사로 검증되지 않는다. ThinkPad의 검사 소스·출력은 `/tmp/vldb26-fig5-preflight-9xguh4em/`, DELL의 검사 소스·출력은 DELL의 `/tmp/vldb26-fig5-preflight-87k7uq6o/`에 임시 보관했다. DELL 사양 조회 및 검사 결과의 로컬 사본은 ThinkPad의 `/tmp/vldb26-fig5-dell-preflight-gc8bjgg6/`에 있다. 공통 검사 소스의 SHA-256은 `c2f6237b423634207e97f0c17647f1c9dfbeb985e01b26ba784039dc80faf469`이다.

원본 실행 절차를 현재 컴퓨터에 맞추려면 다음 사항을 반영해야 한다.

1. **로컬 실행기를 준비한다.** [bench_buffer_mgr.py](experiments/bench_buffer_mgr.py)는 `10.0.21.51`, `~/ringding/`, `sudo` 등 저자 서버 구성을 전제로 한다. 그림 5에 해당하는 YCSB 설정과 libaio 실행은 주석 처리되어 있고 다른 실험은 활성화되어 있다. 따라서 README 예제를 그대로 실행해 그림 5의 열 개 항목이 실행될 것으로 기대하면 안 된다. 그림 5만 선택하는 로컬 실행기를 두는 편이 명확하다. 로컬 바이너리 직접 실행에는 distexprunner, PostgreSQL, vmcache 서브모듈이 필요하지 않다.

2. **현재 CPU에 맞춰 빌드한다.** [CMakeLists.txt](CMakeLists.txt)의 `-mavx512f -mavx512bw`를 제거하고 `-march=native`를 사용한다. 현재 컴파일러로 옵션을 조회했을 때 원본 옵션은 실제로 AVX-512를 활성화했다. 미지원 명령이 생성될 수 있으므로 이 상태의 바이너리를 그대로 실행하는 것은 적절하지 않다. `libs/liburing`은 저장소가 지정한 `4ee26f88a0592675bf623b76e116124956a048ba`를 초기화하고 configure를 명시적으로 수행해 컴파일러 설정을 확인한다. CMake의 외부 프로젝트 configure 명령은 비어 있지만, liburing 자체 Makefile에도 설정 파일을 생성하는 규칙이 있다. 빌드 타깃은 `buffer_mgr`로 제한한다.

3. **libaio 비교 바이너리를 별도로 준비한다.** [kuring.hpp](src/buffer_mgr/kuring.hpp)는 현재 `using Reactor = UringReactor`로 고정되어 있다. [buffer_mgr.cpp](src/buffer_mgr/buffer_mgr.cpp)는 `cfg.libaio == mini::LIBAIO`를 검사하므로, 현재 바이너리에 `--libaio true`만 전달하면 libaio로 전환되지 않는다. 별도 소스/빌드에서 `LibaioReactor`를 선택하거나, 최소한의 빌드 옵션을 추가해 두 바이너리를 명확히 나누어야 한다. 나머지 소스와 최적화 옵션은 같게 유지한다.

4. **사용 가능한 CPU를 명시한다.** 기본 `core_id=64`는 현재 컴퓨터에 없다. 처음 일곱 항목은 예를 들어 `--core_id 2`처럼 확인된 P-core 논리 CPU를 명시할 수 있다. SQPoll을 나중에 실행할 때는 추가 확인이 필요하다. 원본은 SQPoll 스레드를 `core_id+1`에 고정하지만 현재 CPU 2와 3은 같은 물리 코어의 SMT 형제다. CPU 2와 4처럼 서로 다른 물리 P-core에 두려면 SQPoll CPU를 따로 지정하도록 최소한의 설정 확장이 필요하다.

5. **새 일반 파일로 작은 기능 실험부터 실행한다.** [bm.cpp](src/buffer_mgr/bm.cpp)는 일반 경로를 `O_DIRECT | O_RDWR`로 열며 `O_CREAT`를 사용하지 않는다. 따라서 ext4 위에 새 실험 디렉토리와 파일을 먼저 만들고 공간을 할당해야 한다. 예를 들어 여유 공간을 다시 확인한 뒤 새 파일에 8 GiB를 할당할 수 있다. 이는 실험용 저장 공간의 예시이며 버퍼 풀 크기를 8 GiB로 바꾸는 것이 아니다. 기능 확인에서는 데이터와 버퍼 풀을 함께 줄여 읽기·퇴거 쓰기가 실제로 발생하도록 한다. 파일에 쓰는 결과는 원본의 raw block device 결과와 I/O 경로 차이가 있다는 점을 기록한다.

6. **메모리 등록 한도를 준비하고 본 실험을 실행한다.** `+RegBufs`는 1 GiB 버퍼 풀 전체를 등록한다. 벤치마크 프로세스에 충분한 memlock 한도나 필요한 권한을 부여한 뒤 등록 성공을 확인한다. 현재 hard limit도 8 MiB이므로 일반 셸에서 `ulimit -l unlimited`만 실행해서 해결된다고 가정하면 안 된다. 버퍼 풀을 작게 줄여 등록을 통과시키면 다른 워크로드 조건이 되므로 본 비교에서는 1 GiB를 유지한다.

7. **원본 데이터와 새 결과를 분리하여 수집한다.** 실행별로 명령, 바이너리/소스 식별값, 커널, CPU 배치, 전력 조건, 파일시스템, 원시 stdout/stderr와 종료 상태를 남긴다. 기본 점검 이후에는 아래의 열 개 설정 중 실행 가능한 항목을 각각 독립 실행한다. 로딩 시간과 측정 구간을 분리하고, 실패한 설정을 0 TPS 성공 결과로 바꾸지 않는다. 단계 간 비교는 같은 파일 경로 종류, 데이터 크기, 빌드 조건과 전력 조건에서 수행한다.

8. **원본 방식의 집계와 반복 실험 결과를 함께 제시한다.** 원본 설정은 로딩 후 10초, 반복 1회이고, 플롯은 마지막 통계 샘플을 선택한다. 원본을 따라가는 값은 이 방식으로 만들되, 노트북의 변동을 확인하기 위해 추가로 30~60초 측정과 3~5회 반복을 권한다. 추가 결과의 평균·중앙값·범위는 원본 방식과 구분해서 표시한다. 실행 순서를 바꾸어 열과 SSD 상태 변화의 영향을 확인하는 것도 도움이 된다.

9. **전체 열 개 항목은 실험용 NVMe 장치를 확보한 뒤 진행한다.** 실험 장치의 마운트, swap, 데이터 사용 여부를 확인하고, 그 장치의 block 경로와 namespace 문자 경로를 대응시킨다. IOPoll을 위해 NVMe polling queue를 준비하고 실제 완료 경로를 확인한다. 부팅 설정 변경이 필요할 수 있으며, 현재 운영체제 디스크를 사용하는 중에 드라이버를 강제로 내리는 방식으로 처리해서는 안 된다. SQPoll 항목에서는 추가 물리 코어 사용을 기록한다. 같은 실험 장치에서 1~10번을 다시 측정해야 서로 연결된 비교가 된다.

설정별 인자는 다음과 같이 고정할 수 있다. 원본 [실험 코드](experiments/bench_buffer_mgr.py)와 [플롯의 분류 조건](experiments/plot_buffer_mgr.R)을 함께 대조한 표다. CLI의 불리언 값은 `true`/`false`로 전달한다.

모든 항목의 공통 인자는 `--workload ycsb --virt_size 1073741824 --free_target 0.10 --page_table_factor 2.5 --ycsb_tuple_count 10000000 --ycsb_read_ratio 0 --duration 10000 --stats_interval 1000000`이며, 여기에 확인한 `--ssd`와 `--core_id`를 지정한다.

| 항목 | concurrency | evict_batch | sync_variant | posix_variant | submit_always | reg_ring / reg_fds / reg_bufs | nvme_cmds | iopoll | setup_mode | libaio |
|---|---:|---:|---|---|---|---|---|---|---|---|
| Posix Sync. | 1 | 1 | true | true | false | false / false / false | false | false | defer | false |
| io_uring Sync. | 1 | 1 | true | false | false | false / false / false | false | false | defer | false |
| +BatchEvict | 1 | 128 | true | false | false | false / false / false | false | false | defer | false |
| libaio +Fibers | 128 | 128 | false | false | true | false / false / false | false | false | defer | true |
| io_uring +Fibers | 128 | 128 | false | false | true | false / false / false | false | false | defer | false |
| +BatchSubmit | 128 | 128 | false | false | false | false / false / false | false | false | defer | false |
| +RegBufs | 128 | 128 | false | false | false | true / true / true | false | false | defer | false |
| +Passthru | 128 | 128 | false | false | false | true / true / true | true | false | defer | false |
| +IOPoll | 128 | 128 | false | false | false | true / true / true | true | true | defer | false |
| +SQPoll | 128 | 128 | false | false | false | true / true / true | true | true | sqpoll | false |

`+RegBufs`라는 막대에 대응하는 구현은 버퍼뿐 아니라 파일과 링도 등록한다. 세 옵션을 함께 활성화해야 제공된 원본 데이터와 설정이 대응한다. 위 표의 libaio 행은 libaio용으로 빌드한 바이너리로 실행해야 한다.

빌드 준비와 새 파일 할당을 완료한 뒤, 첫 항목의 실행 형태는 아래와 같다. 이 문서 작성 중에는 실행하지 않았으며, 현재 저장소에 이 예시의 바이너리나 데이터 파일을 생성하지도 않았다. `FIG5_DATA_FILE`은 각 호스트에서 NVMe 위에 새로 준비한 실험 전용 일반 파일의 절대 경로로 미리 설정해야 한다. 예를 들어 ThinkPad에서는 NVMe에 있는 현재 저장소 아래의 새 전용 디렉토리, DELL에서는 사용자 지정 `/mnt/nvme0n1p1` 아래의 새 전용 디렉토리를 사용한다. 경로 문자열과 실제 마운트·장치의 대응을 확인한 뒤 파일을 할당한다.

```bash
./build-fig5/buffer_mgr \
  --ssd "${FIG5_DATA_FILE:?새 실험 전용 일반 파일의 절대 경로를 지정하세요}" \
  --core_id 2 \
  --workload ycsb \
  --virt_size 1073741824 \
  --free_target 0.10 \
  --page_table_factor 2.5 \
  --ycsb_tuple_count 10000000 \
  --ycsb_read_ratio 0 \
  --duration 10000 \
  --stats_interval 1000000 \
  --concurrency 1 \
  --evict_batch 1 \
  --sync_variant true \
  --posix_variant true \
  --submit_always false \
  --reg_ring false \
  --reg_fds false \
  --reg_bufs false \
  --nvme_cmds false \
  --iopoll false \
  --setup_mode defer \
  --libaio false
```

공통 인자에서 `virt_size`라는 이름을 그대로 사용한 이유는 코드가 이것을 실제 메모리 슬롯 수 계산에 사용하기 때문이다. `phys_size`라는 다른 옵션 이름을 보고 버퍼 풀 크기를 바꾸면 의도한 조건을 만들지 못할 수 있다. 또 `duration`은 밀리초, `stats_interval`은 마이크로초이므로, 위 설정은 로딩 후 10초 동안 약 1초 간격으로 통계를 출력한다. 통계 출력 스레드도 별도로 존재하므로, 논문의 단일 코어 설명은 트랜잭션/I/O 작업 코어에 대한 설명으로 이해해야 한다.

재현의 정확성을 위해 소스와 논문 사이의 작은 차이도 기록해야 한다. 현재 [ycsb_workload.hpp](src/buffer_mgr/ycsb_workload.hpp)의 `tx()`는 `getRand(0, 100)` 결과에 대해 `rnd <= read_ratio`이면 읽기를 실행한다. [random_generator.hpp](src/buffer_mgr/tpcc/random_generator.hpp)의 난수 범위는 `[0,100)`이다. 따라서 원본의 `ycsb_read_ratio=0`은 현재 코드 경로상 약 1% 읽기와 약 99% 업데이트가 된다. 이는 소스 분석 결과이며 실제 실행 비율을 계측한 것은 아니다. 제공 아티팩트의 설정을 따라가는 재현에서는 우선 0을 유지하고 이 차이를 명시해야 한다. 논문 설명의 엄밀한 100% 업데이트를 적용하는 실험은 비교 조건을 수정한 별도 실험으로 기록하는 편이 타당하다.

플롯도 로컬 결과용 처리가 필요하다. [plot_buffer_mgr.R](experiments/plot_buffer_mgr.R)은 `data/bench_buffer_mgr.csv`를 읽고 `out/plot_buffer_mgr.pdf`를 쓴다. 그대로 사용하면 기존 원본 결과를 읽거나 기존 PDF를 덮어쓸 수 있으므로 새 결과 경로를 명시해야 한다. 원본 스크립트는 `2.05x` 화살표 문자열과 y축 상한을 고정하며, 그림 5 뒤에 TPC-C 플롯도 생성한다. 로컬 재현용 플롯에서는 그림 5 부분만 사용하고, 배율을 실제 값으로 계산하며, 미실행 세 항목을 명시해야 한다. R 의존성을 준비하는 대신 현재 설치된 Python matplotlib로 같은 항목의 막대그래프를 생성하는 방법도 있다.

이번 점검에서는 논문과 코드의 대응, 제공 데이터의 원본 수치, ThinkPad와 DELL의 하드웨어·소프트웨어 준비 상태 및 같은 소스를 사용한 작은 io_uring 등록 검사를 확인했다. 저장소의 실행 코드나 원본 측정 데이터는 변경하지 않았다. DBMS 빌드, 데이터 로딩, 일반 파일 I/O 벤치마크, raw NVMe 쓰기, 시스템 설정 변경과 본 성능 측정은 수행하지 않았다. 다음 구현 범위는 앞의 7개 항목을 위한 CPU 호환 빌드, 두 I/O 백엔드의 분리 빌드, ThinkPad·DELL 공통 실행기와 호스트별 결과 수집·플롯이다. 양쪽 모두 AVX-512 강제 옵션 제거와 memlock 한도 준비가 필요하며, DELL은 실험 데이터 파일이 SATA 대신 NVMe에 위치하도록 설정해야 한다. 전체 NVMe 경로는 양쪽 모두 현재 사용 중인 namespace에 직접 쓰지 않도록 실험용 장치를 확보하고 polling을 준비한 뒤 판정한다.
