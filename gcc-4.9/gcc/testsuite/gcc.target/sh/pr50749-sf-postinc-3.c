/* PR target/50749: Verify that post-increment addressing is generated
   inside a loop.  */
/* { dg-do compile }  */
/* { dg-options "-O2" } */
/* { dg-skip-if "" { "sh*-*-*" } { "-m1" "-m2" "-m3" "-m4al" "*nofpu" "-m4-340*" "-m4-400*" "-m4-500*" "-m5*" } { "" } }  */
/* { dg-final { scan-assembler-times "fmov.s\t@r\[0-9]\+\\+,fr\[0-9]\+" 1 } } */

float
test_func_00 (float* p, int c)
{
  float r = 0;
  do
  {
    r += *p++;
  } while (--c);
  return r;
}
