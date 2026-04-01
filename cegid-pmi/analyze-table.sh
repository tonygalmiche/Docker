#!/bin/bash

# Script pour analyser une table spécifique de SQL Server
# Usage: ./analyze-table.sh NOM_TABLE

# Charger la configuration
source "$(dirname "$0")/config.sh"

# Vérifier si le nom de la table est fourni
if [ -z "$1" ]; then
    echo "❌ Erreur: Nom de table requis"
    echo "Usage: $0 NOM_TABLE"
    echo "Exemple: $0 dbo.ARTICLE"
    exit 1
fi

TABLE_NAME="$1"

echo "📊 Analyse de la table: $TABLE_NAME"
echo "Base de données: $DB_NAME"
echo "================================================"
echo ""

# Requête SQL pour analyser les colonnes de la table
SQL_QUERY="
SET NOCOUNT ON;

-- Vérifier si la table existe
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.TABLES 
    WHERE TABLE_NAME = '$TABLE_NAME' 
       OR CONCAT(TABLE_SCHEMA, '.', TABLE_NAME) = '$TABLE_NAME'
)
BEGIN
    PRINT '❌ Erreur: Table $TABLE_NAME introuvable!'
    PRINT ''
    PRINT 'Tables disponibles:'
    SELECT TABLE_SCHEMA + '.' + TABLE_NAME AS TableName
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
    ORDER BY TABLE_NAME;
END
ELSE
BEGIN
    -- Obtenir le schéma complet
    DECLARE @FullTableName NVARCHAR(256);
    DECLARE @Schema NVARCHAR(128);
    DECLARE @Table NVARCHAR(128);
    
    IF CHARINDEX('.', '$TABLE_NAME') > 0
    BEGIN
        SET @Schema = PARSENAME('$TABLE_NAME', 2);
        SET @Table = PARSENAME('$TABLE_NAME', 1);
    END
    ELSE
    BEGIN
        SELECT @Schema = TABLE_SCHEMA, @Table = TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_NAME = '$TABLE_NAME';
    END
    
    PRINT 'Colonnes de la table ' + @Schema + '.' + @Table + ':';
    PRINT REPLICATE('-', 120);
    PRINT '';
    
    -- Pour chaque colonne, obtenir les informations et le nombre de valeurs distinctes
    DECLARE @ColumnName NVARCHAR(128);
    DECLARE @DataType NVARCHAR(128);
    DECLARE @MaxLength INT;
    DECLARE @IsNullable VARCHAR(3);
    DECLARE @Position INT;
    DECLARE @SQL NVARCHAR(MAX);
    DECLARE @DistinctCount INT;
    DECLARE @TotalCount INT;
    DECLARE @RawDataType NVARCHAR(128);
    DECLARE @ColExpr NVARCHAR(256);
    
    -- Obtenir le nombre total de lignes
    SET @SQL = N'SELECT @Count = COUNT(*) FROM [' + @Schema + N'].[' + @Table + N']';
    EXEC sp_executesql @SQL, N'@Count INT OUTPUT', @TotalCount OUTPUT;
    
    PRINT 'Nombre total de lignes: ' + CAST(@TotalCount AS VARCHAR(20));
    PRINT '';
    
    -- Table temporaire pour stocker les stats avant tri
    CREATE TABLE #ColStats (
        ColumnName  NVARCHAR(128),
        DataType    NVARCHAR(128),
        IsNullable  VARCHAR(3),
        DistinctCount INT NULL,
        Percentage  DECIMAL(5,2) NULL
    );
    
    DECLARE column_cursor CURSOR FOR
    SELECT 
        COLUMN_NAME,
        DATA_TYPE,
        DATA_TYPE + 
        CASE 
            WHEN DATA_TYPE IN ('varchar', 'char', 'nvarchar', 'nchar') 
            THEN '(' + CAST(CHARACTER_MAXIMUM_LENGTH AS VARCHAR(10)) + ')'
            WHEN DATA_TYPE IN ('decimal', 'numeric')
            THEN '(' + CAST(NUMERIC_PRECISION AS VARCHAR(10)) + ',' + CAST(NUMERIC_SCALE AS VARCHAR(10)) + ')'
            ELSE ''
        END AS DataType,
        CHARACTER_MAXIMUM_LENGTH,
        IS_NULLABLE,
        ORDINAL_POSITION
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = @Schema AND TABLE_NAME = @Table
    ORDER BY ORDINAL_POSITION;
    
    OPEN column_cursor;
    FETCH NEXT FROM column_cursor INTO @ColumnName, @RawDataType, @DataType, @MaxLength, @IsNullable, @Position;
    
    WHILE @@FETCH_STATUS = 0
    BEGIN
        -- Compter les valeurs distinctes pour cette colonne
        IF @RawDataType IN ('text', 'ntext', 'image')
            SET @ColExpr = N'CAST([' + @ColumnName + N'] AS NVARCHAR(MAX))';
        ELSE
            SET @ColExpr = N'[' + @ColumnName + N']';
        SET @SQL = N'SET ANSI_WARNINGS OFF; SELECT @Count = COUNT(DISTINCT ' + @ColExpr + N') FROM [' + @Schema + N'].[' + @Table + N']';
        
        BEGIN TRY
            EXEC sp_executesql @SQL, N'@Count INT OUTPUT', @DistinctCount OUTPUT;
            
            DECLARE @Percentage DECIMAL(5,2);
            IF @TotalCount > 0
                SET @Percentage = (CAST(@DistinctCount AS DECIMAL(18,2)) / @TotalCount) * 100
            ELSE
                SET @Percentage = 0;
            
            INSERT INTO #ColStats VALUES (@ColumnName, @DataType, @IsNullable, @DistinctCount, @Percentage);
        END TRY
        BEGIN CATCH
            INSERT INTO #ColStats VALUES (@ColumnName, @DataType, @IsNullable, NULL, NULL);
        END CATCH
        
        FETCH NEXT FROM column_cursor INTO @ColumnName, @RawDataType, @DataType, @MaxLength, @IsNullable, @Position;
    END
    
    CLOSE column_cursor;
    DEALLOCATE column_cursor;
    
    -- Affichage trié par valeurs distinctes décroissantes
    PRINT 'Colonne                          | Type                  | Null | Valeurs distinctes | % unique';
    PRINT REPLICATE('-', 120);
    
    DECLARE print_cursor CURSOR FOR
    SELECT ColumnName, DataType, IsNullable, DistinctCount, Percentage
    FROM #ColStats
    ORDER BY DistinctCount DESC;
    
    DECLARE @PDistinctCount INT;
    DECLARE @PPercentage DECIMAL(5,2);
    
    OPEN print_cursor;
    FETCH NEXT FROM print_cursor INTO @ColumnName, @DataType, @IsNullable, @PDistinctCount, @PPercentage;
    
    WHILE @@FETCH_STATUS = 0
    BEGIN
        IF @PDistinctCount IS NOT NULL
            PRINT 
                LEFT(@ColumnName + REPLICATE(' ', 32), 32) + ' | ' +
                LEFT(@DataType + REPLICATE(' ', 21), 21) + ' | ' +
                LEFT(@IsNullable + REPLICATE(' ', 4), 4) + ' | ' +
                RIGHT(REPLICATE(' ', 18) + CAST(@PDistinctCount AS VARCHAR(18)), 18) + ' | ' +
                RIGHT(REPLICATE(' ', 7) + CAST(@PPercentage AS VARCHAR(7)), 7) + '%';
        ELSE
            PRINT 
                LEFT(@ColumnName + REPLICATE(' ', 32), 32) + ' | ' +
                LEFT(@DataType + REPLICATE(' ', 21), 21) + ' | ' +
                LEFT(@IsNullable + REPLICATE(' ', 4), 4) + ' | ' +
                'Erreur calcul';
        
        FETCH NEXT FROM print_cursor INTO @ColumnName, @DataType, @IsNullable, @PDistinctCount, @PPercentage;
    END
    
    CLOSE print_cursor;
    DEALLOCATE print_cursor;
    DROP TABLE #ColStats;
    
    PRINT '';
END
"

# Exécuter la requête
docker exec -i $CONTAINER_NAME /opt/mssql-tools18/bin/sqlcmd \
    -S localhost \
    -U $DB_USER \
    -P "$DB_PASSWORD" \
    -d $DB_NAME \
    -C \
    -Q "$SQL_QUERY"

echo ""
echo "================================================"
echo "✅ Analyse terminée!"
