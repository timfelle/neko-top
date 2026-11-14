# Check that each `steady` simulation component writes its convergence data to
# the file it names, and that one naming none writes the default file.
#
# The case has three `steady` components that never converge. The first names
# `steady_first.csv` and writes a row every step, the second names
# `steady_second.csv` and writes every second step, and the third names no
# file and writes every third step. The files are removed before the run,
# since the component appends to a file that already exists. Each file must
# then hold exactly one header, so that it had a single writer, and the rows
# of the component that named it.
#
#   cmake -DDRIVER=<driver> -DCASE_FILE=<case> -DSTEPS=<n> \
#         -P check_steady_output_filename.cmake
#
# DRIVER     The driver to run the case with.
# CASE_FILE  The case file.
# STEPS      The number of time steps the case takes.

foreach(var DRIVER CASE_FILE STEPS)
    if (NOT DEFINED ${var})
        message(FATAL_ERROR "${var} is not set")
    endif()
endforeach()

# The file and the log frequency of each component, in the order of the case
set(files steady_first.csv steady_second.csv steady_state_data.csv)
set(frequencies 1 2 3)

file(REMOVE ${files})

execute_process(COMMAND ${DRIVER} ${CASE_FILE} RESULT_VARIABLE result)
if (NOT result EQUAL 0)
    message(FATAL_ERROR "The run of ${CASE_FILE} failed: ${result}")
endif()

set(failed FALSE)
foreach(file frequency IN ZIP_LISTS files frequencies)
    if (NOT EXISTS "${file}")
        message(STATUS "${file}: not written")
        set(failed TRUE)
        continue()
    endif()

    file(STRINGS "${file}" lines)
    set(headers ${lines})
    list(FILTER headers INCLUDE REGEX "^iter,time,u,v,w,p,scalar$")
    list(LENGTH headers n_headers)
    list(LENGTH lines n_lines)
    math(EXPR n_rows "${n_lines} - ${n_headers}")
    math(EXPR expected_rows "${STEPS} / ${frequency}")

    message(STATUS "${file}: ${n_headers} header(s), expected 1; "
        "${n_rows} row(s), expected ${expected_rows}")
    if (NOT n_headers EQUAL 1 OR NOT n_rows EQUAL expected_rows)
        set(failed TRUE)
    endif()
endforeach()

if (failed)
    message(FATAL_ERROR "The steady components did not write their own files")
endif()
