variable a
variable b
variable c
variable count
variable ch

: store-input
    ch load 48 -
    count load 0 =
    if
        a store
    else
        count load 1 =
        if
            b store
        else
            c store
        then
    then
    count load 1 + count store
;

:interrupt on-input
    read-char ch store
    store-input
;

: sort-ab
    a load b load >
    if
        a load b load a store b store
    then
;

: sort-bc
    b load c load >
    if
        b load c load b store c store
    then
;

: print-sorted
    a load 48 + write-char
    32 write-char
    b load 48 + write-char
    32 write-char
    c load 48 + write-char
    10 write-char
;

: main
    ei
    begin
        count load 3 =
    until
    sort-ab
    sort-bc
    sort-ab
    print-sorted
;
