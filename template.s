.global _start
.section .text

// template for a simple program that adds two numbers and exits

_start:
    mov x0, #42 // first number
    mov x1, #7  // second number
    add x2, x0, x1 // add the two numbers and store the result in x2

    // exit the program
    mov x8, #93 // syscall number for exit
    mov x0, #0  // exit status code
    svc #0
