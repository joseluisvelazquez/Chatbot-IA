-- SOLO DATOS FAKE DE PRUEBA PAYMENT REMINDERS - SIGA / BRIDGE DB
-- NO USAR PARA CLIENTES REALES
-- REVISAR SELECT ANTES DE EJECUTAR DELETE
-- NO USAR TRUNCATE
-- NO USAR DELETE SIN WHERE

START TRANSACTION;

SELECT cuenta, cod_cli, saldo, pagos_minimos, fecha_venta, estatus, proceso
FROM cuentas
WHERE cuenta IN ('A900001', 'B900002', 'A900003')
   OR cod_cli IN ('TESTCLI900001', 'TESTCLI900002', 'TESTCLI900003');

SELECT folio, no_cuenta, identificador, nombre_completo, tel_1, fecha_venta
FROM bitacora_ventas
WHERE folio IN ('990001', '990002', '990003')
   OR no_cuenta IN ('A900001', 'B900002', 'A900003')
   OR identificador IN ('TESTCLI900001', 'TESTCLI900002', 'TESTCLI900003');

SELECT cod_cliente, nombre_completo, tel1, telefonodl
FROM clientes
WHERE cod_cliente IN ('TESTCLI900001', 'TESTCLI900002', 'TESTCLI900003');

DELETE FROM estados_cuenta
WHERE cuenta_e IN ('A900001', 'B900002', 'A900003')
   OR id_item IN ('TESTPM900001', 'TESTPM900002', 'TESTPM900003');

DELETE FROM bitacora_ventas
WHERE folio IN ('990001', '990002', '990003')
   OR no_cuenta IN ('A900001', 'B900002', 'A900003')
   OR identificador IN ('TESTCLI900001', 'TESTCLI900002', 'TESTCLI900003');

DELETE FROM cuentas
WHERE cuenta IN ('A900001', 'B900002', 'A900003')
   OR cod_cli IN ('TESTCLI900001', 'TESTCLI900002', 'TESTCLI900003');

DELETE FROM clientes
WHERE cod_cliente IN ('TESTCLI900001', 'TESTCLI900002', 'TESTCLI900003');

SELECT COUNT(*) AS fake_siga_rows_remaining
FROM (
  SELECT cuenta AS marker FROM cuentas
  WHERE cuenta IN ('A900001', 'B900002', 'A900003')
     OR cod_cli IN ('TESTCLI900001', 'TESTCLI900002', 'TESTCLI900003')
  UNION ALL
  SELECT no_cuenta AS marker FROM bitacora_ventas
  WHERE folio IN ('990001', '990002', '990003')
     OR no_cuenta IN ('A900001', 'B900002', 'A900003')
     OR identificador IN ('TESTCLI900001', 'TESTCLI900002', 'TESTCLI900003')
  UNION ALL
  SELECT cod_cliente AS marker FROM clientes
  WHERE cod_cliente IN ('TESTCLI900001', 'TESTCLI900002', 'TESTCLI900003')
) fake_rows;

COMMIT;
