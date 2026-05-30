variable a-hi
variable a-lo
variable b-hi
variable b-lo
variable sum-hi
variable sum-lo

: add64
    a-lo load b-lo load + sum-lo store
    a-hi load b-hi load + sum-hi store
;

: main
    1 a-hi store
    5 a-lo store
    1 b-hi store
    7 b-lo store
    add64
    sum-hi load 48 + write-char
    58 write-char
    sum-lo load 10 / 48 + write-char
    sum-lo load 10 mod 48 + write-char
    10 write-char
;
