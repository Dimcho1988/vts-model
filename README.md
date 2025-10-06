# vts-model

Streamlit приложение за **Velocity–Time–Distance** модел (идеална крива + персонализация чрез процентно отклонение), изчисление на резултати за **3 и 12 мин**, и критична скорост (**CS**) + **W' (D')**. Включена е автоматична модулация на кривата според разликата между личното и идеалното W'.

## Стартиране локално
```bash
pip install -r requirements.txt
streamlit run main/app.py
```
(или от корена на проекта: `streamlit run vts-model/main/app.py`)

## Файлове
- `main/app.py` – Streamlit интерфейс
- `main/model_utils.py` – интерполации и моделна логика
- `main/ideal_distance_time_speed.csv` – идеални данни (може да се замени с ваши)
