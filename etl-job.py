import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
import pandas as pd
from sklearn.experimental import enable_iterative_imputer  # habilita IterativeImputer
from sklearn.impute import IterativeImputer

## @params: [JOB_NAME]
args = getResolvedOptions(sys.argv, ['JOB_NAME'])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)
job.commit()

#  Parámetros de entrada
DB_NAME       = "db-woman-stem-latam"
TABLE_STUD    = "estudiantes_stem_clean_aws_csv"
TABLE_PERS    = "personal_acad_mico_stem__clean_aws_csv"
TARGET_BUCKET = "s3://target-woman-stem-latam/"
year_cols     = ['2013','2014','2015','2016','2017','2018','2019','2020','2021','2022']

#  Leer desde el Catálogo
#    Creamos DynamicFrames y los convertimos a Spark DataFrames
df_students = glueContext.create_dynamic_frame.from_catalog(
    database=DB_NAME, table_name=TABLE_STUD
).toDF()

df_personal = glueContext.create_dynamic_frame.from_catalog(
    database=DB_NAME, table_name=TABLE_PERS
).toDF()

# Asegurarnos de que las columnas de año sean numéricas
for c in year_cols:
    df_students = df_students.withColumn(c, df_students[c].cast("double"))
    df_personal = df_personal.withColumn(c, df_personal[c].cast("double"))

#  Función para aislar solo los % de cada año en Spark
def aislar_porcentajes(df):
    """Selecciona únicamente las columnas de año."""
    return df.select(*year_cols)

df_est_students = aislar_porcentajes(df_students)
df_est_personal = aislar_porcentajes(df_personal)

# 7. Convertir a pandas para aplicar IterativeImputer (MICE)

pdf_students = df_est_students.toPandas()
pdf_personal = df_est_personal.toPandas()

# 8. Función genérica de imputación MICE
def imputar_mice(df_pdf):
    """
    Toma un DataFrame pandas con las columnas year_cols,
    aplica IterativeImputer y devuelve un pandas.DataFrame
    con los mismos nombres de columna.
    """
    imputer = IterativeImputer(random_state=0)
    arr = imputer.fit_transform(df_pdf)
    return pd.DataFrame(arr, columns=df_pdf.columns)

# 9. Ejecutamos la imputación
students_mice_pdf = imputar_mice(pdf_students)
personal_mice_pdf = imputar_mice(pdf_personal)

# 10. Reconstruir Spark DataFrames juntando IDs + columnas imputadas

id_cols_students = df_students.columns[:2]
id_cols_personal = df_personal.columns[:2]

# Convertir pandas imputado de vuelta a Spark DataFrame
spark_students_mice = spark.createDataFrame(
    pd.concat([df_students.select(*id_cols_students).toPandas(),
               students_mice_pdf], axis=1)
)

spark_personal_mice = spark.createDataFrame(
    pd.concat([df_personal.select(*id_cols_personal).toPandas(),
               personal_mice_pdf], axis=1)
)

# 11. Escribir los resultados en Parquet en el bucket de destino
spark_students_mice.write.mode("overwrite") \
    .parquet(f"{TARGET_BUCKET}estudiantes_mice/")

spark_personal_mice.write.mode("overwrite") \
    .parquet(f"{TARGET_BUCKET}personal_mice/")


# ——————————————————————————————————————————————————————————————
# OPCIÓN CSV CON SPARK
# Descomenta estas líneas  y comenta el punto 11 si prefieres exportar en formato CSV
# spark_students_mice.write.mode("overwrite") \
#     .option("header", "true") \
#     .csv(f"{TARGET_BUCKET}estudiantes_mice_csv/")

# spark_personal_mice.write.mode("overwrite") \
#     .option("header", "true") \
#     .csv(f"{TARGET_BUCKET}personal_mice_csv/")
# ——————————————————————————————————————————————————————————————

# 12. Finalizar el Job
job.commit()
