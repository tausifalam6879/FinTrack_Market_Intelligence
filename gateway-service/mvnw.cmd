@echo off
setlocal
set "MAVEN_VERSION=3.9.16"
set "WRAPPER_ROOT=%USERPROFILE%\.m2\wrapper\dists\fintrack-apache-maven-%MAVEN_VERSION%"
set "MAVEN_COMMAND=%WRAPPER_ROOT%\apache-maven-%MAVEN_VERSION%\bin\mvn.cmd"

if exist "%MAVEN_COMMAND%" goto run
where mvn >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  mvn %*
  exit /b %ERRORLEVEL%
)

if not exist "%WRAPPER_ROOT%" mkdir "%WRAPPER_ROOT%"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$url='https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.16/apache-maven-3.9.16-bin.zip';" ^
  "$expected='ed41650d42485cfc243fad22158caf9cbb5dc408ce7a09ddb94dd42a019de929ca43065bfa450612cf12bf78b5cafa3884b96c090de326ff590448c933454af3';" ^
  "$destination='%WRAPPER_ROOT%'; $archive=Join-Path $destination 'apache-maven.zip';" ^
  "Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive;" ^
  "$actual=(Get-FileHash -LiteralPath $archive -Algorithm SHA512).Hash.ToLowerInvariant();" ^
  "if($actual -ne $expected){throw 'Downloaded Maven archive checksum did not match.'};" ^
  "Expand-Archive -LiteralPath $archive -DestinationPath $destination -Force; Remove-Item -LiteralPath $archive"
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

:run
call "%MAVEN_COMMAND%" %*
exit /b %ERRORLEVEL%
