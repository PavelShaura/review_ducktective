import Markdown from "react-markdown";

interface Props {
  text: string;
}

/**
 * Ответ агента разметкой.
 *
 * Модель отвечает на Markdown: списки, выделения, фрагменты кода в тройных
 * кавычках. Показанный как простой текст, он читается хуже, чем сказан, —
 * звёздочки и решётки спорят с содержимым за внимание.
 *
 * Сырой HTML не разбирается: `react-markdown` этого по умолчанию не делает,
 * а ответ модели — не тот текст, которому стоит разрешать теги.
 */
export function Answer({ text }: Props) {
  return (
    <div className="answer">
      <Markdown>{text}</Markdown>
    </div>
  );
}
