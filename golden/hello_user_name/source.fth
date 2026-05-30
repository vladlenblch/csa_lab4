variable name-base
variable name-len
variable done
variable ch

: type-pstr
    dup load swap 1 +
    swap 0 do
        dup i + load write-char
    loop
    drop
;

: print-name
    name-base load 1 +
    name-len load 0 do
        dup i + load write-char
    loop
    drop
;

:interrupt on-input
    read-char ch store
    ch load 10 =
    if
        1 done store
    else
        ch load name-base load 1 + name-len load + store
        name-len load 1 + name-len store
    then
;

: main
    s"?????" name-base store
    s"What is your name?" type-pstr
    10 write-char
    ei
    begin
        done load
    until
    s"Hello, " type-pstr
    print-name
    33 write-char
    10 write-char
;
