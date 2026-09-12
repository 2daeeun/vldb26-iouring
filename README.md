# High-Performance DBMSs with io_uring: When and How to Use It

그림 5 실험은 **`dbms`(기존 코드, TPS)** 또는 **`fio`(I/O 경로 비교, IOPS)**를
선택해서 실행한다. DBMS는 10개 항목과 fibers를 사용하고, fio는 버퍼 풀·fibers가
없는 9개 항목을 비교한다. fio 결과는 논문의 TPS를 직접 재현한 결과가 아니다.

아래 명령은 수정된 소스와 `6.15.11-io_uring` 커널이 준비된 **DELL의 같은 터미널**에서
순서대로 실행한다. **Raw 실험은 `/dev/nvme0n1`에 쓰기를 수행한다.
마운트·swap 등에 사용하지 않는 실험 전용 SSD만 지정한다.**

**1. 실행 방식을 선택하고 준비한다.**

```bash
cd /home/leedaeeun/Documents/github/vldb26-iouring
# 최초 1회: 아래 파일에 sudo 비밀번호를 한 줄로 입력하고 저장한다.
test -e password.conf || install -m 600 password.conf.example password.conf
chmod 600 password.conf
nano password.conf

FIG5_METHOD=fio  # 기존 DBMS 실험은 dbms로 변경

if [[ "$FIG5_METHOD" == dbms ]]; then
  python3 experiments/build_fig5.py --jobs 16
  FIG5_RUN=(--duration-ms 10000 --order paper)
else
  fio --version
  FIG5_RUN=(--duration-ms 30000 --ramp-seconds 5 --order rotate)
fi

hostname
lsblk -d -o NAME,MODEL,SERIAL /dev/nvme0n1
FIG5_ARGS=(
  --method "$FIG5_METHOD" --storage raw-nvme
  --nvme-block /dev/nvme0n1 --nvme-char /dev/ng0n1
  --cpu 24 --numa-node 1 --sqpoll-cpu 25 --min-pcie-width 4
)
```

DELL 식별값은 hostname `arch`, SSD 일련번호 `S4EWNM0W327482P`다.
fio 방식은 설치된 fio를 사용하므로 별도 fio 빌드가 필요 없다.
`password.conf`는 **실험을 실행하는 컴퓨터의 저장소 루트**에 둔다. 비밀번호만 한 줄로
입력하거나 `PASSWORD=비밀번호` 형식을 사용한다(따옴표로 감싸지 않는다).
`sudo_exec.sh`가 이 파일로 인증하고 memlock 2 GiB를 설정하므로 직접 sudo를 붙이지 않는다.
설정 파일은 Git에서 제외되며, 다른 컴퓨터의 비밀번호 파일을 자동으로 가져오지 않는다.

**2. 사전 점검을 한다.**

```bash
./sudo_exec.sh experiments/run_fig5.py "${FIG5_ARGS[@]}" --preflight
```

`"errors": []`일 때 진행한다. 사전 점검은 장치에 쓰거나 실험 결과를 만들지 않는다.
NVMe polling queue가 준비되어 있어야 한다. 점검 통과가 커널 패치 적용을 증명하지는 않는다.

**3. 작은 기능 검사를 실행한다.**

```bash
./sudo_exec.sh experiments/run_fig5.py "${FIG5_ARGS[@]}" \
  --confirm-device /dev/nvme0n1 --smoke
```

DBMS는 10개, fio는 9개 항목이 모두 `PASS`, 마지막 상태가 `COMPLETE`인지 확인한다.
항목당 3초의 작은 검사이므로 논문 성능과 비교하지 않는다.

**4. 본 실험을 실행한다.**

```bash
FIG5_RESULT="$PWD/results/figure5/dell-${FIG5_METHOD}-r10-$(date +%Y%m%d-%H%M%S)"
./sudo_exec.sh experiments/run_fig5.py "${FIG5_ARGS[@]}" "${FIG5_RUN[@]}" \
  --confirm-device /dev/nvme0n1 --repeats 10 --output-dir "$FIG5_RESULT"
```

**1회씩 실행하려면 `--repeats 1`로 변경한다.** DBMS 기본 조건은 레코드 1천만 개,
버퍼 풀 1 GiB, 비동기 항목 128 fibers다. fio는 8 GiB 범위, 4 KiB 무작위 읽기·쓰기
50:50, 비동기 QD 128이며, 초기화 후 항목별 5초 워밍업과 30초 측정을 수행한다.
실제 옵션·성공 여부는 결과에 기록된다. 다른 벤치마크나 빌드를 동시에 실행하지 않는다.
결과 폴더는 실행기가 생성하므로 미리 만들지 않고, 재실행할 때 새 경로를 사용한다.

**5. 그래프를 만든다.**

```bash
./sudo_exec.sh experiments/plot_fig5.py "$FIG5_RESULT"
```

DBMS는 `figure5-last.png`, fio는 `fio-comparison-randrw.png`가 생성된다(PDF·SVG도 제공).
`summary.csv`는 반복별 결과, `run.json`은 실행 조건이다. 그래프는 반복의 중앙값과
최솟값~최댓값을 표시한다. 사전 점검만 하거나 경로 변수만 지정하면 그래프를 만들 수 없다.
새 터미널에서는 변수와 실제 결과 경로를 다시 지정한다.

상세 설명: [fio 설계·옵션·결과 해석](experiments/FIG5_FIO_KO.md),
[DBMS 파일 모드](experiments/FIG5_DELL_KO.md), [DBMS raw 모드](experiments/FIG5_NVME_KO.md),
[IOPoll 분석과 커널 패치](experiments/FIG5_DELL_X4_ANALYSIS_20260912_KO.md).
