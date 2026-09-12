add_subdirectory(mt)

set(BUFFER_MGR_UTIL_SOURCES
    tpcc/random_generator.cpp
    tpcc/types.cpp
    tpcc/tpcc_globals.cpp

    btree.cpp
    config.cpp
    bm.cpp

)

# Reactor types occur in shared headers and in bm.cpp. Compile the entire
# buffer-manager library separately for each backend, not only main().
foreach(BACKEND IN ITEMS uring libaio)
    if(BACKEND STREQUAL "uring")
        set(EXE_NAME buffer_mgr)
        set(UTILS_NAME buffer_mgr_utils)
        set(USE_LIBAIO 0)
    else()
        set(EXE_NAME buffer_mgr_libaio)
        set(UTILS_NAME buffer_mgr_libaio_utils)
        set(USE_LIBAIO 1)
    endif()
    add_library(${UTILS_NAME} ${BUFFER_MGR_UTIL_SOURCES})
    target_compile_definitions(${UTILS_NAME} PUBLIC BUFFER_MGR_USE_LIBAIO=${USE_LIBAIO})
    target_link_libraries(${UTILS_NAME} PUBLIC utils liburing boost_fiber aio)
    add_executable(${EXE_NAME} buffer_mgr.cpp)
    target_link_libraries(${EXE_NAME} PRIVATE ${UTILS_NAME})
endforeach()
