cmake_minimum_required(VERSION 3.16)
set(CMAKE_C_STANDARD 11)

set(BLUEPAD32_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../third_party/bluepad32)
set(ENV{BTSTACK_ROOT} ${BLUEPAD32_ROOT}/external/btstack)

# btstack (copiado por tools/setup-bluepad32.ps1 para src/components/btstack), bluepad32 e protocolo comum
set(EXTRA_COMPONENT_DIRS ${BLUEPAD32_ROOT}/src/components ${CMAKE_CURRENT_SOURCE_DIR}/../common)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ds5_side)
