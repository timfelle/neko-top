
mkdir -p mem_test/fail mem_test/pass
rm -fr mem_test/fail/* mem_test/pass/*

FAILED_FILES=$(find logs/mem_test -name output.log)
for f in $FAILED_FILES; do
    JOBID=$(grep -E "Job ID:" $f | awk {'printf $3'})
    [ -z "$JOBID" ] && continue
    if ! grep JobID,JobName,State,ExitCode,NNodes,NTasks,ReqMem,Elapsed,MaxRSS,MaxRSSTask,MaxRSSNode,AveRSS,MaxVMSize,TRESUsageInMax $f 1>/dev/null ; then
        sacct -j "$JOBID" --parsable2 --delimiter=, --noconvert \
            --format=JobID,JobName,State,ExitCode,NNodes,NTasks,ReqMem,Elapsed,MaxRSS,MaxRSSTask,MaxRSSNode,AveRSS,MaxVMSize,TRESUsageInMax \
            >> $f
    fi
    mkdir -p mem_test/fail/$(basename $(dirname $f))
    cp -f $f $(dirname $f)/error.log -t mem_test/fail/$(basename $(dirname $f))
done

PASS_FILES="$(find results/mem_test -name output.log)"
for f in $PASS_FILES; do
    JOBID=$(grep -E "Job ID:" $f | awk {'printf $3'})
    [ -z "$JOBID" ] && continue
    if ! grep JobID,JobName,State,ExitCode,NNodes,NTasks,ReqMem,Elapsed,MaxRSS,MaxRSSTask,MaxRSSNode,AveRSS,MaxVMSize,TRESUsageInMax $f 1>/dev/null ; then
        sacct -j "$JOBID" --parsable2 --delimiter=, --noconvert \
            --format=JobID,JobName,State,ExitCode,NNodes,NTasks,ReqMem,Elapsed,MaxRSS,MaxRSSTask,MaxRSSNode,AveRSS,MaxVMSize,TRESUsageInMax \
            >> $f
    fi
    mkdir -p mem_test/pass/$(basename $(dirname $f))
    cp -f $f -t mem_test/pass/$(basename $(dirname $f))
done