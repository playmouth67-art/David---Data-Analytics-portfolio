-- =====================================================================
-- 06_agente_dictamenes.sql  --  Tabla de dictámenes del agente
-- =====================================================================
-- Es la ÚNICA tabla que el servidor MCP escribe. Deliberadamente no toca
-- ninguna de las tablas que produce el proceso ETL: el agente opina sobre
-- los datos, no los modifica.
--
-- Por qué existe: un agente que clasifica sin dejar rastro no es usable en
-- producción. Nadie puede revisar sus decisiones, nadie puede medir si
-- acierta, y nadie puede revertirlas. Cada dictamen guarda qué se clasificó,
-- con qué criterio, con cuánta confianza y cuándo.
--
-- El campo revisado_por queda para el humano que valida. Mientras esté en
-- NULL, el dictamen es una hipótesis del modelo, no una decisión del negocio.
--
-- Uso:
--   docker exec -i etl_visitas_mysql mysql -uetl -petl etl_visitas < sql/06_agente_dictamenes.sql
-- =====================================================================

USE etl_visitas;

CREATE TABLE IF NOT EXISTS dictamen_agente (
  id_dictamen     BIGINT AUTO_INCREMENT PRIMARY KEY,

  -- Qué caso se dictaminó
  tipo_caso       VARCHAR(60)  NOT NULL COMMENT 'Tipo de ambigüedad, según visitas_casos_ambiguos',
  email           VARCHAR(320) NOT NULL COMMENT 'Llave natural del registro, junto con fecha_envio',
  fecha_envio     DATETIME     NOT NULL,

  -- Qué decidió el agente
  clasificacion   ENUM('VALIDO','SOSPECHOSO','ERROR_DE_ORIGEN','REQUIERE_NEGOCIO') NOT NULL,
  justificacion   VARCHAR(1000) NOT NULL COMMENT 'La evidencia en la que se apoya el veredicto',
  confianza       DECIMAL(3,2)  NOT NULL COMMENT 'De 0.00 a 1.00; sirve para priorizar la revisión',

  -- Rastro
  fecha_dictamen  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revisado_por    VARCHAR(100) NULL COMMENT 'NULL mientras ningún humano lo haya validado',
  fecha_revision  DATETIME     NULL,
  veredicto_humano ENUM('CONFIRMA','CORRIGE','DESCARTA') NULL,

  INDEX idx_caso (tipo_caso),
  INDEX idx_registro (email, fecha_envio),
  INDEX idx_pendientes (revisado_por, confianza)
) ENGINE=InnoDB
  COMMENT='Clasificaciones del agente sobre casos que el ETL dejó marcados como ambiguos';
