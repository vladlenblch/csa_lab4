variable best
variable left
variable right
variable product
variable number
variable reversed

: digit
    48 + write-char
;

: write-result
    best load 100000 / 10 mod digit
    best load 10000 / 10 mod digit
    best load 1000 / 10 mod digit
    best load 100 / 10 mod digit
    best load 10 / 10 mod digit
    best load 10 mod digit
;

: palindrome?
    product load number store
    0 reversed store
    begin
        reversed load 10 * number load 10 mod + reversed store
        number load 10 / number store
        number load 0 =
    until
    product load reversed load =
;

: update-best
    product load best load >
    if
        product load best store
    then
;

: main
    0 best store
    91 82 do
        i 11 * left store
        1000 900 do
            i right store
            left load right load * product store
            palindrome?
            if
                update-best
            then
        loop
    loop
    write-result
;
