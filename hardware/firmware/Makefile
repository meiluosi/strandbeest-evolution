CXX ?= g++
test: test/host_test.cpp lib/rigcore/rigcore.h
	$(CXX) -std=c++17 -Wall -Wextra -O1 -o /tmp/rigcore_host_test test/host_test.cpp
	/tmp/rigcore_host_test
.PHONY: test
