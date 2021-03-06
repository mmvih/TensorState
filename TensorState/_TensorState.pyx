# distutils: language=c++
cimport cython
cimport numpy as np
import numpy as np

IF UNAME_SYSNAME == "Windows":
    cdef extern from "immintrin.h":
        ctypedef int __m256i
        ctypedef float __m256

        __m256 _mm256_loadu_ps(np.float32_t* __A) nogil
        __m256 _mm256_setzero_ps()
        int _mm256_movemask_ps(__m256 __A) nogil
ELSE:
    cdef extern from "x86intrin.h":
        ctypedef int __m256i
        ctypedef float __m256

        __m256 _mm256_loadu_ps(np.float32_t* __A) nogil
        __m256 _mm256_setzero_ps()
        int _mm256_movemask_ps(__m256 __A) nogil

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.initializedcheck(False)
cdef void  byte_sort(unsigned char [:,:] states,
                     unsigned long long [:] index,
                     unsigned long long start,
                     unsigned long long end,
                     unsigned long long col,
                     long long [:] counts) nogil:

    # Create an index view for fast rearranging of indices
    cdef unsigned long long [:] index_view = index

    # Initialize counting and offset indices
    cdef unsigned long long i
    for i in range(256):
        counts[i] = 0

    cdef unsigned long long offsets[256]

    cdef unsigned long long next_offset[256]

    # Count values
    for i in range(start,end):
        counts[(states[index[i],col])] += 1

    # Calculate cumulative sum and offsets
    cdef unsigned long long num_partitions = 0
    cdef unsigned long long remaining_partitions[256]
    cdef unsigned long long total = 0
    cdef unsigned long long count
    for i in range(256):
        count = counts[i]
        if count:
            offsets[i] = total
            total += count
            remaining_partitions[num_partitions] = i
            num_partitions += 1
        
        next_offset[i] = total

    # Swap index values into place
    cdef unsigned long long val, v
    cdef unsigned long long ind, offset, temp
    for i in range(0,num_partitions-1):
        val = remaining_partitions[i]
        while offsets[val] < next_offset[val]:
            ind = offsets[val]
            v = states[index[start+ind],col]
            if v==val:
                offsets[val] += 1
                continue
            offset = offsets[v]
            offsets[v] += 1
            temp = index_view[start+ind]
            index_view[start+ind] = index_view[start+offset]
            index_view[start+offset] = temp

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.nonecheck(False)
cdef void _lex_sort(unsigned char [:,:] states,
                    unsigned long long [:] index,
                    unsigned long long start,
                    unsigned long long end,
                    unsigned long long col,
                    list bin_edges):

    cdef unsigned long long total = 0
    cdef unsigned long long i
    cdef long long counts[256]

    if col > 0:
        byte_sort(states, index, start, end, col, counts)
        for i in range(256):
            if counts[i]<=1:
                if counts[i] == 1:
                    bin_edges.append(bin_edges[len(bin_edges)-1] + counts[i])
                total += counts[i]
                continue
            _lex_sort(states, index, start+total, start+total+counts[i], col-1, bin_edges)
            total += counts[i]
    else:
        byte_sort(states, index, start, end, col, counts)
        for c in counts:
            if c > 0:
                bin_edges.append(bin_edges[len(bin_edges)-1] + c)

cpdef lex_sort(unsigned char [:,:] states,
               unsigned long long state_count):

    index = np.arange(states.shape[0],dtype=np.uint64)

    bin_edges = [0]

    _lex_sort(states,index,0,state_count,states.shape[1]-1,bin_edges)

    return np.asarray(bin_edges,dtype=np.uint64),index

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.initializedcheck(False)
cdef void _compress_tensor(const float[:,:] input, unsigned char [:,:] result) nogil:

    # Initialize variables
    cdef __m256 substate
    cdef long long rows, cols, row, col, col_shift, col_floor, i
    cdef unsigned int value_truncate = 0xFFFF
    
    # Get the number of rows and cols in the input
    rows,cols = input.shape[0], input.shape[1]
    
    cdef unsigned char shift = cols % 8
    for col in range(0,cols-shift,8):
        col_shift = col
        col_floor = col_shift//8
        for row in range(rows):
            substate = _mm256_loadu_ps(&input[row,col_shift])
            result[row,col_floor] = _mm256_movemask_ps(substate) ^ value_truncate
    
    if shift > 0:
        col_shift = cols - shift
        col_floor = col_shift//8
        value_truncate = 0
        for i in range(shift):
            value_truncate += 2**i
            
        for row in range(rows):
            substate = _mm256_loadu_ps(&input[row,col_shift])
            mask = _mm256_movemask_ps(substate)
            result[row,col_floor] = (mask ^ 0xFFFF) & value_truncate

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.initializedcheck(False)
cpdef np.ndarray compress_tensor(const float [:,:] input):
    # Initialize the output
    rows,cols = input.shape[0], input.shape[1]
    result = np.zeros((rows,int(np.ceil(cols/8))), dtype = np.uint8)

    # Call the nogil method
    _compress_tensor(input,result)

    return result