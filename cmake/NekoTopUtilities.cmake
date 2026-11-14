# Utility functions for Neko-TOP CMake scripts
#
# This file contains utility functions that are used in the CMake scripts for
# Neko-TOP. It is included in the main CMakeLists.txt file and can be used by
# other CMake scripts in the project.

# Prepend the pkg-config directories of one or more installation prefixes to
# the PKG_CONFIG_PATH environment variable. FindPkgConfig searches the
# environment PKG_CONFIG_PATH before the CMAKE_PREFIX_PATH entries, so without
# this the configured prefixes (JSON_FORTRAN_DIR, NEKO_DIR, HDF5_ROOT,
# including their defaults under ${EXTERNAL_DIR}) lose to any matching .pc
# file already on it.
# Callers run restore_pkg_config_path() once the package has been resolved,
# so the prefixes cannot leak into later lookups. Accepts any number of
# prefixes (e.g. NEKO_DIR plus HDF5_ROOT, so a single pkg_check_modules(neko)
# call can resolve a `Requires: hdf5_fortran`); an empty prefix is ignored,
# so callers may pass an unset/empty variable unconditionally.
function(prepend_pkg_config_path)
    # Record the previous value, and whether it was set at all, for
    # restore_pkg_config_path().
    if (DEFINED ENV{PKG_CONFIG_PATH})
        set(_had_pkg_config_path TRUE PARENT_SCOPE)
        set(_saved_pkg_config_path "$ENV{PKG_CONFIG_PATH}" PARENT_SCOPE)
    else()
        set(_had_pkg_config_path FALSE PARENT_SCOPE)
    endif()

    set(_dirs)
    foreach(_prefix ${ARGN})
        if (NOT "${_prefix}" STREQUAL "")
            foreach(_sub lib/pkgconfig lib64/pkgconfig share/pkgconfig)
                if (IS_DIRECTORY "${_prefix}/${_sub}")
                    list(APPEND _dirs ${_prefix}/${_sub})
                endif()
            endforeach()
        endif()
    endforeach()

    if (_dirs)
        string(REPLACE ";" ":" _path "${_dirs}")
        if (DEFINED ENV{PKG_CONFIG_PATH})
            set(_path "${_path}:$ENV{PKG_CONFIG_PATH}")
        endif()
        set(ENV{PKG_CONFIG_PATH} "${_path}")
    endif()
endfunction()

# Restore PKG_CONFIG_PATH to the state recorded by prepend_pkg_config_path(),
# unsetting it again if it was not set before.
function(restore_pkg_config_path)
    if (_had_pkg_config_path)
        set(ENV{PKG_CONFIG_PATH} "${_saved_pkg_config_path}")
    else()
        unset(ENV{PKG_CONFIG_PATH})
    endif()
endfunction()

# Clear a cache variable if the named environment variable differs from the
# value it held on the previous configure of this build directory, so that
# the variable gets freshly re-derived from the (changed) environment.
#
# set(<var> <value> CACHE <type> <docstring>) without FORCE only ever
# initializes a cache entry the first time it is seen; every later configure
# of the same build directory it is a silent no-op even if $ENV{<env_name>}
# has since changed. JSON_FORTRAN_DIR/NEKO_DIR are both derived this way from
# JSON_FORTRAN_DIR/NEKO_DIR environment variables (the way prepare.env and
# setup.sh normally supply them), so without this, changing either in the
# environment and reconfiguring an existing build directory never reaches
# <var> at all -- let alone the pkg_check_modules() lookup that uses it.
# Call this immediately before the if(DEFINED ENV{<env_name>}) .../set(<var>
# ... CACHE ...) cascade that resolves <var>.
function(reset_cache_if_env_changed var env_name)
    set(_tracking_var "_neko_top_last_env_${env_name}")
    if (DEFINED ENV{${env_name}})
        set(_current "$ENV{${env_name}}")
    else()
        set(_current "")
    endif()
    if (DEFINED ${_tracking_var} AND NOT "${${_tracking_var}}" STREQUAL "${_current}")
        message(STATUS
            "${env_name} changed (was '${${_tracking_var}}', now '${_current}'); "
            "forcing ${var} to be re-derived")
        unset(${var} CACHE)
    endif()
    # FORCE: this is our own bookkeeping cache entry, which must track the
    # current environment value every configure, not just the first one that
    # created it.
    set(${_tracking_var} "${_current}" CACHE INTERNAL
        "Last ${env_name} environment value seen" FORCE)
endfunction()

# Force FindPkgConfig to redo pkg_check_modules(<pkg> ...) on this configure
# if its install prefix changed since the previous one.
#
# pkg_check_modules() caches its result (<pkg>_FOUND and friends, plus the
# internal __pkg_config_checked_<pkg>/__pkg_config_arguments_<pkg> bookkeeping
# variables) keyed only on the literal module-list/options passed to it, never
# on PKG_CONFIG_PATH or CMAKE_PREFIX_PATH. So reconfiguring an existing build
# directory with a changed JSON_FORTRAN_DIR/NEKO_DIR calls pkg_check_modules()
# with the exact same arguments as before and silently keeps the stale,
# already-cached link from the previous prefix. Call this before
# pkg_check_modules(<pkg> ...), passing the prefix just resolved for it, to
# detect that change ourselves and clear the cache entries that gate
# FindPkgConfig's own "already resolved" check, forcing a fresh lookup.
function(force_pkg_config_recheck_on_prefix_change pkg prefix)
    set(_tracking_var "_neko_top_last_${pkg}_prefix")
    if (DEFINED ${_tracking_var} AND NOT "${${_tracking_var}}" STREQUAL "${prefix}")
        message(STATUS
            "${pkg}'s install prefix changed (was '${${_tracking_var}}', now "
            "'${prefix}'); forcing pkg-config to re-resolve ${pkg}")
        unset("__pkg_config_checked_${pkg}" CACHE)
        unset("__pkg_config_arguments_${pkg}" CACHE)
        unset("${pkg}_FOUND" CACHE)
    endif()
    # FORCE: this is our own bookkeeping cache entry, which must track the
    # current prefix every configure, not just the first one that created it.
    set(${_tracking_var} "${prefix}" CACHE INTERNAL
        "Last install prefix used to resolve ${pkg} via pkg-config" FORCE)
endfunction()