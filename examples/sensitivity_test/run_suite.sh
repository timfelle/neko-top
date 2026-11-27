#!/bin/bash

ROOT_DIR=$(dirname $(realpath $0))
RUN_DIR=$1
SCALE=${2:-c}
EXPERIMENTS="111 001 010 100"

echo "Running sensitivity test for scale $SCALE" > $RUN_DIR/$SCALE-report.txt
for EXP in $EXPERIMENTS; do
    printf "_%.0s" {1..80} >> $RUN_DIR/$SCALE-report.txt
    printf "\nRunning sensitivity test for experiment $SCALE-$EXP\n" >> $RUN_DIR/$SCALE-report.txt
    python3 $ROOT_DIR/sd_report.py $RUN_DIR/$SCALE-$EXP >> $RUN_DIR/$SCALE-report.txt
    python3 $ROOT_DIR/dissipation_split.py $RUN_DIR/$SCALE-$EXP >> $RUN_DIR/$SCALE-report.txt
    python3 $ROOT_DIR/fluid_sensitivity.py $RUN_DIR/$SCALE-$EXP >> $RUN_DIR/$SCALE-report.txt
    python3 $ROOT_DIR/overintegration_check.py $RUN_DIR/$SCALE-$EXP >> $RUN_DIR/$SCALE-report.txt
done

printf "_%.0s" {1..80} >> $RUN_DIR/$SCALE-report.txt
printf "\nRunning weight scan for experiment $SCALE\n" >> $RUN_DIR/$SCALE-report.txt
python3 $ROOT_DIR/weight_scan.py $RUN_DIR/$SCALE-111 \
    $RUN_DIR/$SCALE-001 $RUN_DIR/$SCALE-010 $RUN_DIR/$SCALE-100 \
    >> $RUN_DIR/$SCALE-report.txt