import re
import pandas as pd

class PccG0vMerger:
    def __init__(self, pcc_tender_df, pcc_award_df, g0v_tender_df, g0v_award_df):
        self.pcc_tender_df = pcc_tender_df
        self.pcc_award_df = pcc_award_df
        self.g0v_tender_df = g0v_tender_df
        self.g0v_award_df = g0v_award_df



    def remove_spaces_around_chinese(self, text):
        '''
        #test this
        txt = "正立螢光電動顯微觀察系統 如CARL ZEISS AXIO IMAGER M2 或同等品以上 詳規範 共1ST"
        remove_spaces_around_chinese(txt)
        '''
        # Define a pattern to match Chinese characters
        chinese_char_pattern = re.compile(r'[\u4e00-\u9fff]')

        # Split the text by spaces
        parts = text.split()

        # Remove spaces around Chinese characters
        cleaned_parts = []
        for part in parts:

            if cleaned_parts and chinese_char_pattern.search(part):
                cleaned_parts[-1] += part

            elif cleaned_parts and chinese_char_pattern.search(cleaned_parts[-1][-1]):
                    # Append English parts without space if previous part was Chinese
                cleaned_parts[-1] += part

            else:
                cleaned_parts.append(part)

        # Join the cleaned parts with spaces
        cleaned_text = ' '.join(cleaned_parts)

        return cleaned_text

 
    def clean_g0v_titles_in_df(self, df):
        if 'title' in df.columns:
            df['title'] = df['title'].apply(self.remove_spaces_around_chinese)
        return df 



    @staticmethod
    def ensure_columns(df, columns):
        df = df.copy()
        for col in columns:
            if col not in df.columns:
                df[col] = pd.Series(dtype='object')
        # date is int on populated frames; keep empty ones mergeable with them
        if df.empty:
            df['date'] = df['date'].astype('int64')
        return df


    def run_merger(self):
        g0v_tender_df = self.clean_g0v_titles_in_df(self.g0v_tender_df)
        g0v_award_df = self.clean_g0v_titles_in_df(self.g0v_award_df)


        #Check empty dataframe
        empty_tender_df = pd.DataFrame(columns=self.pcc_tender_df.columns)
        empty_award_df = pd.DataFrame(columns=self.pcc_award_df.columns)
        g0v_tender_df = g0v_tender_df if not g0v_tender_df.empty else empty_tender_df
        g0v_award_df = g0v_award_df if not g0v_award_df.empty else empty_award_df

        # A source that returned nothing (e.g. site unreachable) has no columns;
        # add the merge keys so the merge doesn't KeyError.
        tender_keys = ['date', 'title', 'keyword', 'job_number', '機關名稱', '領投開標:截止投標', 'url']
        award_keys = ['date', 'title', 'keyword', 'type', 'job_number', '機關名稱', 'url']
        pcc_tender_df = self.ensure_columns(self.pcc_tender_df, tender_keys)
        pcc_award_df = self.ensure_columns(self.pcc_award_df, award_keys)
        g0v_tender_df = self.ensure_columns(g0v_tender_df, tender_keys)
        g0v_award_df = self.ensure_columns(g0v_award_df, award_keys)

        # Outer merge gov and g0v data
        merged_tender_df = pcc_tender_df.merge(g0v_tender_df, on=tender_keys, how='outer')
        merged_award_df = pcc_award_df.merge(g0v_award_df, on=award_keys, how='outer')

        return merged_tender_df, merged_award_df
    