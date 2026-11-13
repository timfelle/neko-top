# Check that the MMA and the design HDF5 checkpoints refuse, on every rank, to
# load into a run they do not match, rather than overrunning a buffer, failing
# on some ranks only or hanging.
#
#   cmake -DDRIVER=<exe> -DMPIEXEC=<launcher> -DNUMPROC_FLAG=<flag> \
#         [-DPREFLAGS=<flags>] -DMAX_RANKS=<n> -DTIME_LIMIT=<seconds> \
#         -P check_checkpoint_rank_change.cmake
#
# DRIVER      The checkpoint_rank_change executable.
# MPIEXEC     The MPI launcher, with NUMPROC_FLAG and PREFLAGS as for pFUnit.
# MAX_RANKS   The number of ranks available. The case that needs three ranks
#             is skipped below that.
# TIME_LIMIT  The time limit of each run, in seconds. A run that does not stop
#             within it hangs, which fails the test.
#
# Each case saves both checkpoints on some ranks and loads each of them on
# others. A load must stop with the expected error on every rank: the driver
# makes each rank wait for the others before it stops, so the output holds
# one message per rank, and an error raised on some ranks only hangs.

foreach(var DRIVER MPIEXEC NUMPROC_FLAG MAX_RANKS TIME_LIMIT)
    if (NOT DEFINED ${var})
        message(FATAL_ERROR "${var} is not set")
    endif()
endforeach()

set(checkpoint "checkpoint_rank_change.h5")
set(rank_count_error "checkpoint was written with a different number of ranks")
set(failed FALSE)

# Run the driver on `ranks` ranks and return its exit code and output.
function(run_driver ranks mode layout result_var output_var)
    execute_process(
        COMMAND ${MPIEXEC} ${PREFLAGS} ${NUMPROC_FLAG} ${ranks}
            ${DRIVER} ${mode} ${checkpoint} ${layout}
        RESULT_VARIABLE result
        OUTPUT_VARIABLE output
        ERROR_VARIABLE output
        TIMEOUT ${TIME_LIMIT}
    )
    set(${result_var} "${result}" PARENT_SCOPE)
    set(${output_var} "${output}" PARENT_SCOPE)
endfunction()

# Count the occurrences of `pattern` in `text`.
function(count_matches pattern text count_var)
    string(REGEX MATCHALL "${pattern}" matches "${text}")
    list(LENGTH matches count)
    set(${count_var} ${count} PARENT_SCOPE)
endfunction()

# Save on `save_ranks` ranks, then load each checkpoint on `load_ranks` ranks
# with the given layout, and require `expected` from every loading rank.
function(check_case save_ranks load_ranks layout expected)
    set(case "saved on ${save_ranks}, loaded on ${load_ranks} ${layout}")
    message(STATUS "Case: ${case}")

    file(REMOVE ${checkpoint})
    run_driver(${save_ranks} save even result output)
    count_matches("save completed on rank" "${output}" completed)
    if (NOT result EQUAL 0 OR NOT completed EQUAL save_ranks)
        message(STATUS "${output}")
        message(STATUS "FAIL: save (exit: ${result}, completed on "
            "${completed} of ${save_ranks} ranks)")
        set(failed TRUE PARENT_SCOPE)
        return()
    endif()

    foreach(kind mma design)
        run_driver(${load_ranks} load_${kind} ${layout} result output)
        count_matches("${kind}: ${expected}" "${output}" errors)
        count_matches("load_${kind} completed" "${output}" completed)
        if (NOT result MATCHES "^[0-9]+$")
            # A hang past the time limit, or a crash
            message(STATUS "${output}")
            message(STATUS "FAIL: ${kind} load: ${result}")
            set(failed TRUE PARENT_SCOPE)
        elseif (result EQUAL 0 OR NOT errors EQUAL load_ranks
                OR NOT completed EQUAL 0)
            message(STATUS "${output}")
            message(STATUS "FAIL: ${kind} load (exit: ${result}, expected "
                "error on ${errors} of ${load_ranks} ranks, completed on "
                "${completed})")
            set(failed TRUE PARENT_SCOPE)
        else()
            message(STATUS "${kind}: error on ${errors} of ${load_ranks} "
                "ranks, as expected")
        endif()
    endforeach()
endfunction()

# Fewer ranks than the save: the stored per-rank sizes no longer fit.
check_case(2 1 even "${rank_count_error}")

# More ranks than the save.
check_case(1 2 even "${rank_count_error}")

# The same number of ranks, but one rank holds a different share. Only some
# ranks see their own size differ, so all must agree before reading on.
if (MAX_RANKS GREATER_EQUAL 3)
    check_case(3 3 uneven "mismatch in n during HDF5 read")
else()
    message(STATUS "Skipping the uneven case, which needs 3 ranks")
endif()

file(REMOVE ${checkpoint})

if (failed)
    message(FATAL_ERROR "A checkpoint was loaded into a run it does not match")
endif()
